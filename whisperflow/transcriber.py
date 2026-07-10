"""ASR engine: local speech-to-text via faster-whisper.

This replaces Wispr Flow's cloud ASR with a fully local Whisper model
(CTranslate2 backend). The model is downloaded once on first run and
cached in ~/.cache/huggingface.
"""

import numpy as np
from faster_whisper import WhisperModel

# Discard clips shorter than this — accidental key taps produce no speech.
MIN_AUDIO_SECONDS = 0.3


class Transcriber:
    # Default to CPU: "auto" picks CUDA whenever an NVIDIA GPU is present,
    # which crashes unless the CUDA 12 runtime (cublas64_12.dll) is installed.
    def __init__(self, model_size: str = "base.en", device: str = "cpu",
                 compute_type: str = "int8"):
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio: np.ndarray, language: str | None = None,
                   initial_prompt: str | None = None) -> str:
        """initial_prompt biases recognition toward the words it contains —
        used for the custom vocabulary (product names, jargon)."""
        if audio.size < int(MIN_AUDIO_SECONDS * 16000):
            return ""
        segments, _info = self.model.transcribe(
            audio,
            language=language,
            beam_size=5,
            vad_filter=True,  # trims silence so hold-and-think doesn't hallucinate
            initial_prompt=initial_prompt,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
