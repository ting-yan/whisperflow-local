"""ASR engine: local speech-to-text via faster-whisper.

This replaces Wispr Flow's cloud ASR with a fully local Whisper model
(CTranslate2 backend). The model is downloaded once on first run and
cached in ~/.cache/huggingface.

Runs on the NVIDIA GPU when one is usable and falls back to the CPU when
it isn't — see _prepare_cuda_dlls() and the device="auto" path below.
"""

import os
import sys
import sysconfig
import threading
from pathlib import Path

# Hugging Face's "Xet" fast-download backend (hf_xet) intermittently 401s on
# its CAS storage service even for public models (huggingface/xet-core#404).
# Must be set before faster_whisper pulls in huggingface_hub, since the flag
# is read once at import time. Falls back to the plain HTTPS downloader.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def _prepare_cuda_dlls():
    """Make the pip-installed CUDA 12 runtime loadable by CTranslate2.

    nvidia-cublas-cu12 / nvidia-cudnn-cu12 drop their DLLs in
    site-packages/nvidia/<lib>/bin, which is on nobody's search path.
    CTranslate2 loads them with a plain LoadLibrary at first encode, so
    os.add_dll_directory alone is NOT enough — the name has to resolve
    through PATH, or you get "Library cublas64_12.dll is not found or
    cannot be loaded" from the first transcribe(), long after the model
    constructed fine.
    """
    if os.name != "nt":
        return
    roots = {Path(sysconfig.get_paths()["purelib"]) / "nvidia"}
    # PyInstaller builds ship the DLLs next to the exe instead.
    roots.add(Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)) / "nvidia")
    dirs = [str(r / sub / "bin") for r in roots
            for sub in ("cublas", "cudnn", "cuda_nvrtc")
            if (r / sub / "bin").is_dir()]
    if not dirs:
        return
    os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])
    for d in dirs:
        try:
            os.add_dll_directory(d)
        except OSError:
            pass


_prepare_cuda_dlls()

import numpy as np
from faster_whisper import WhisperModel

# Discard clips shorter than this — accidental key taps produce no speech.
MIN_AUDIO_SECONDS = 0.3

# Auto-detect only ever chooses between the user's configured languages
# (whisperflow/languages.py). Whisper's detector ranks all 99, and on short or
# noisy speech the runners-up are junk like "cy"/"nn" rather than a plausible
# second guess — letting one of those win swaps the decoder into a language
# that isn't being spoken and loses the whole utterance.
from whisperflow.languages import DEFAULT_LANGUAGES

# When English is enabled, another language has to *clearly* beat it before
# auto-detect switches, because code-switched speech (Singlish especially) is
# English borrowing a few foreign words: a sentence with some Mandarin in it
# scored en=0.47 / zh=0.52 here, and decoding that as Chinese loses the
# English around it. Requiring a 1.5x lead keeps it in English while genuine
# Chinese (zh=0.998 vs en=0.001 in the same test) still switches. Only tuned
# on EN/ZH; applied to every non-English language on the same reasoning.
DETECT_NON_EN_MARGIN = 1.5

# Singlish isn't a language Whisper knows — there's no token for it, and it's
# recognized as English. All we can do is bias the decoder toward spelling its
# vocabulary correctly, via the initial prompt.
#
# The prompt is a style example as much as a word list: Whisper mimics the
# casing and punctuation it's given. A bare lowercase list of terms makes it
# emit lowercase, unpunctuated text, so the sample sentence below carries the
# capitals and full stops the rest of the dictation should copy.
SINGLISH_TERMS = [
    "lah", "leh", "lor", "meh", "hor", "sia", "liao", "mah", "aiyo", "alamak",
    "walao", "shiok", "makan", "kiasu", "jialat", "tahan", "chope", "paiseh",
    "sabo", "bojio", "atas", "sian", "steady", "chiong", "kena", "ang moh",
    "kopitiam", "hawker", "HDB", "MRT", "can or not",
]
SINGLISH_STYLE = "Wah, this one damn shiok lah! Can or not? He booked liao, paiseh."


def build_prompt(vocabulary=None, singlish: bool = False) -> str | None:
    """Whisper's initial_prompt: the words to favour, written as prose.

    Style transfers from this prompt to the output, so it stays capitalized
    and punctuated — see SINGLISH_TERMS. Note that faster-whisper keeps only
    the LAST ~223 tokens of the prompt, so a long vocabulary silently drops
    its earliest entries; the Singlish terms go last, where they survive.
    """
    words = list(vocabulary or [])
    if singlish:
        words += [w for w in SINGLISH_TERMS if w not in words]
    if not words:
        return SINGLISH_STYLE if singlish else None
    prompt = "Words that may appear: " + ", ".join(words) + "."
    if singlish:
        prompt = "Singlish dictation. " + prompt + " " + SINGLISH_STYLE
    return prompt

# compute_type to use when a device is picked without one being specified.
DEFAULT_COMPUTE_TYPE = {"cuda": "float16", "cpu": "int8"}


class Transcriber:
    """device: "auto" (GPU if it actually works, else CPU), "cuda", or "cpu".

    "auto" is the sane default but it can't just look for an NVIDIA card:
    WhisperModel(device="cuda") constructs happily and only blows up on the
    first encode when the CUDA 12 runtime is missing. So the CUDA attempt is
    validated with a real warm-up encode before it's accepted.
    """

    def __init__(self, model_size: str = "base.en", device: str = "auto",
                 compute_type: str | None = None):
        self.load_error: str | None = None
        if device == "auto":
            # Try the GPU, keep the CPU as the fallback; compute_type (if the
            # config pins one) applies to whichever device actually loads.
            attempts = [("cuda", compute_type or DEFAULT_COMPUTE_TYPE["cuda"]),
                        ("cpu", compute_type or DEFAULT_COMPUTE_TYPE["cpu"])]
        else:
            attempts = [(device, compute_type or DEFAULT_COMPUTE_TYPE.get(device, "default"))]

        for i, (dev, ct) in enumerate(attempts):
            try:
                model = WhisperModel(model_size, device=dev, compute_type=ct)
                self._warmup(model)
            except Exception as exc:  # noqa: BLE001 — any GPU failure means "try CPU"
                if i + 1 == len(attempts):
                    raise
                self.load_error = f"GPU unavailable ({exc}) — running on CPU"
                continue
            self.model = model
            self.device = dev
            self.compute_type = ct
            break

        # Live partial-transcript passes and the final post-release pass can
        # both call transcribe() close together; a single WhisperModel isn't
        # safe under concurrent calls, so serialize them. Re-entrant because
        # transcribe() can call detect_language() while already holding it.
        self._lock = threading.RLock()
        self.reset_detection()

    @staticmethod
    def _warmup(model: WhisperModel):
        """Run one real encode so CUDA failures surface here rather than on
        the user's first dictation, and so the first dictation doesn't eat
        the ~1s of lazy kernel/library loading.

        vad_filter must stay off: on silence the VAD drops every frame and
        the encoder never runs, which would validate nothing.
        """
        tone = (0.1 * np.sin(np.arange(16000) * 0.05)).astype(np.float32)
        segments, _info = model.transcribe(tone, language="en", beam_size=1,
                                           vad_filter=False)
        for _ in segments:  # transcribe() is lazy — drain it to force the work
            break

    def reset_detection(self):
        """Forget the auto-detected language. The app calls this when a new
        recording starts, so detection runs once per utterance instead of on
        every live-partial pass — which also stops the preview from flipping
        script mid-sentence."""
        self._detected: str | None = None

    @property
    def detected_language(self) -> str | None:
        """Language auto-detect settled on for the current utterance, or None
        when nothing has been detected yet (or the language was pinned)."""
        return getattr(self, "_detected", None)

    def detect_language(self, audio: np.ndarray, languages=None) -> str:
        """Best of `languages` for this audio, cached until
        reset_detection(). Costs one encoder pass (~80ms on GPU), or none
        when there's only one language to choose."""
        languages = list(languages or DEFAULT_LANGUAGES)
        if getattr(self, "_detected", None):
            return self._detected
        if not self.model.model.is_multilingual:
            return "en"  # ".en" models have no other option
        if len(languages) == 1:
            self._detected = languages[0]
            return self._detected
        try:
            with self._lock:  # shares the model with in-flight partial passes
                _lang, _prob, all_probs = self.model.detect_language(audio)
            probs = dict(all_probs)
            best = max(languages, key=lambda c: probs.get(c, 0.0))
            if ("en" in languages and best != "en"
                    and probs.get(best, 0.0) <= probs.get("en", 0.0) * DETECT_NON_EN_MARGIN):
                best = "en"
        except Exception:  # noqa: BLE001 — detection is best-effort
            best = languages[0]
        self._detected = best
        return best

    def transcribe(self, audio: np.ndarray, language: str | None = None,
                   initial_prompt: str | None = None, beam_size: int = 5) -> str:
        """initial_prompt biases recognition toward the words it contains —
        used for the custom vocabulary (product names, jargon). Live partial
        passes pass beam_size=1 for speed; the final pass uses the default 5."""
        if audio.size < int(MIN_AUDIO_SECONDS * 16000):
            return ""
        with self._lock:
            if language is None:
                # Never hand language=None to Whisper: its own auto-detect is
                # unrestricted. Pick from the default set ourselves instead
                # (the app resolves the language before calling, so this
                # fallback only matters to scripts like smoke_test.py).
                language = self.detect_language(audio)
            segments, _info = self.model.transcribe(
                audio,
                language=language,
                beam_size=beam_size,
                vad_filter=True,  # trims silence so hold-and-think doesn't hallucinate
                initial_prompt=initial_prompt,
            )
            return " ".join(seg.text.strip() for seg in segments).strip()
