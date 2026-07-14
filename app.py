"""WhisperFlow Local — local push-to-talk dictation with a settings UI.

Hold the hotkey (default F8), speak, release. The transcript is formatted
and pasted into whatever window has focus. The window lets you pick the
microphone, change the hotkey, switch models, and toggle hold-vs-toggle mode.

Run with:  pythonw app.py   (no console)  or  python app.py  (with console)
"""

import json
import re
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

VERSION = "1.2.0"

import tkinter as tk
from tkinter import ttk, messagebox

# Console (if any) may default to cp1252; never let a print crash a callback.
if sys.stdout:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import keyboard
import sounddevice as sd
import pystray
from PIL import Image, ImageDraw

from whisperflow.recorder import Recorder
from whisperflow.transcriber import Transcriber
from whisperflow.formatter import (
    basic_format, AIFormatter, detect_action, suggest_new_vocab, to_simplified,
)
from whisperflow.injector import inject
from whisperflow.updater import check_for_update

# When frozen by PyInstaller, user files (config, log) live next to the exe;
# bundled read-only assets live in the _internal dir (sys._MEIPASS).
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent
ASSET_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))

CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "whisperflow.log"
MODEL_CHOICES = [
    "tiny.en", "tiny", "base.en", "base", "small.en", "small",
    "medium", "large-v3",
]

# Display name -> Whisper language code (None = auto-detect). ".en"-suffixed
# models are English-only and can't use any entry here except "English".
LANGUAGE_CHOICES = [
    ("Auto-detect", None),
    ("English", "en"),
    ("Spanish", "es"),
    ("French", "fr"),
    ("German", "de"),
    ("Italian", "it"),
    ("Portuguese", "pt"),
    ("Dutch", "nl"),
    ("Russian", "ru"),
    ("Chinese", "zh"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
    ("Hindi", "hi"),
    ("Arabic", "ar"),
]
_LANG_DISPLAY_TO_CODE = dict(LANGUAGE_CHOICES)
_LANG_CODE_TO_DISPLAY = {code: name for name, code in LANGUAGE_CHOICES}

PARTIAL_INTERVAL = 1.2  # seconds between live partial-transcript passes
MIN_PARTIAL_AUDIO = 0.6  # seconds — skip partial passes on very short buffers


def log_error(context: str):
    """Append the current exception to a log file — the app usually runs
    windowless (pythonw), so this is the only place tracebacks survive."""
    import traceback
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {context}\n")
            f.write(traceback.format_exc() + "\n")
    except OSError:
        pass
SINGLE_INSTANCE_PORT = 47821
DEFAULT_MIC_LABEL = "System default"


def _make_dot(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img


TRAY_ICONS = {
    "idle": _make_dot((70, 130, 180, 255)),   # steel blue
    "rec": _make_dot((220, 50, 50, 255)),     # red — live recording
    "busy": _make_dot((240, 160, 40, 255)),   # orange — transcribing
}

try:
    import winsound

    def _beep(freq):
        threading.Thread(
            target=winsound.Beep, args=(freq, 90), daemon=True
        ).start()
except ImportError:
    def _beep(freq):
        pass


def list_input_devices():
    """[(index, name)] of input devices. Prefer WASAPI host API on Windows —
    it lists each physical device once, with untruncated names."""
    hostapis = sd.query_hostapis()
    wasapi = next(
        (i for i, h in enumerate(hostapis) if "WASAPI" in h["name"]), None
    )
    devices = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] <= 0:
            continue
        if wasapi is not None and dev["hostapi"] != wasapi:
            continue
        devices.append((idx, dev["name"]))
    return devices


class App:
    def __init__(self, root: tk.Tk, config: dict):
        self.root = root
        self.config = config
        self.recorder = Recorder()
        self.transcriber = None
        self.ai_formatter = None
        self._busy = False
        self._hooks = []
        self._loaded_model = None
        self._last_injected_text = ""

        self._build_ui()
        self._start_tray()
        self._register_hotkey()
        self._load_model_async()
        self._init_ai_cleanup()
        self._check_updates_async()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        self.root.title(f"WhisperFlow Local v{VERSION}")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", False)
        pad = {"padx": 10, "pady": 4}

        frame = ttk.Frame(self.root, padding=10)
        frame.grid(sticky="nsew")

        self.status_var = tk.StringVar(value="Starting...")
        status = ttk.Label(frame, textvariable=self.status_var,
                           font=("Segoe UI", 11, "bold"))
        status.grid(row=0, column=0, columnspan=3, sticky="w", **pad)

        self.transcript_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.transcript_var, wraplength=340,
                  foreground="#555").grid(row=1, column=0, columnspan=3,
                                          sticky="w", **pad)

        ttk.Separator(frame).grid(row=2, column=0, columnspan=3,
                                  sticky="ew", pady=6)

        # Microphone picker
        ttk.Label(frame, text="Microphone:").grid(row=3, column=0,
                                                  sticky="w", **pad)
        self._devices = list_input_devices()
        mic_names = [DEFAULT_MIC_LABEL] + [name for _, name in self._devices]
        current_mic = self.config.get("input_device") or DEFAULT_MIC_LABEL
        if current_mic not in mic_names:
            current_mic = DEFAULT_MIC_LABEL
        self.mic_var = tk.StringVar(value=current_mic)
        mic_box = ttk.Combobox(frame, textvariable=self.mic_var,
                               values=mic_names, state="readonly", width=34)
        mic_box.grid(row=3, column=1, columnspan=2, sticky="w", **pad)

        # Hotkey picker
        ttk.Label(frame, text="Hotkey:").grid(row=4, column=0,
                                              sticky="w", **pad)
        self.hotkey_var = tk.StringVar(value=self.config.get("hotkey", "f8"))
        hotkey_entry = ttk.Entry(frame, textvariable=self.hotkey_var,
                                 state="readonly", width=14)
        hotkey_entry.grid(row=4, column=1, sticky="w", **pad)
        self.capture_btn = ttk.Button(frame, text="Set...",
                                      command=self._capture_hotkey)
        self.capture_btn.grid(row=4, column=2, sticky="w", **pad)

        # Hold-to-talk toggle
        self.hold_var = tk.BooleanVar(
            value=self.config.get("hold_to_talk", True))
        ttk.Checkbutton(
            frame, text="Hold to talk (unchecked = press to start/stop)",
            variable=self.hold_var,
        ).grid(row=5, column=0, columnspan=3, sticky="w", **pad)

        # Model picker
        ttk.Label(frame, text="Model:").grid(row=6, column=0,
                                             sticky="w", **pad)
        self.model_var = tk.StringVar(
            value=self.config.get("model_size", "base.en"))
        ttk.Combobox(frame, textvariable=self.model_var,
                     values=MODEL_CHOICES, state="readonly",
                     width=14).grid(row=6, column=1, sticky="w", **pad)
        ttk.Label(frame, text="(bigger = slower, more accurate)",
                  foreground="#888").grid(row=6, column=2, sticky="w", **pad)

        # Language picker — ".en" models only ever understand English, so
        # picking anything else auto-switches to the multilingual model.
        ttk.Label(frame, text="Language:").grid(row=7, column=0,
                                                sticky="w", **pad)
        lang_values = [name for name, _ in LANGUAGE_CHOICES]
        current_code = self.config.get("language")
        current_display = _LANG_CODE_TO_DISPLAY.get(current_code)
        if current_display is None:
            current_display = current_code or "Auto-detect"
            if current_display not in lang_values:
                lang_values = lang_values + [current_display]
        self.lang_var = tk.StringVar(value=current_display)
        lang_box = ttk.Combobox(frame, textvariable=self.lang_var,
                                values=lang_values, state="readonly",
                                width=14)
        lang_box.grid(row=7, column=1, sticky="w", **pad)
        lang_box.bind("<<ComboboxSelected>>", self._on_language_change)
        self.lang_note_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.lang_note_var,
                  foreground="#a05a2c").grid(row=7, column=2,
                                             sticky="w", **pad)

        # Custom vocabulary
        ttk.Label(frame, text="Vocabulary:").grid(row=8, column=0,
                                                  sticky="w", **pad)
        self.vocab_var = tk.StringVar(
            value=", ".join(self.config.get("vocabulary") or []))
        ttk.Entry(frame, textvariable=self.vocab_var,
                  width=37).grid(row=8, column=1, columnspan=2,
                                 sticky="w", **pad)
        ttk.Label(frame, text="Comma-separated words Whisper should favor "
                              "(names, jargon) — grows automatically when "
                              "AI cleanup corrects a name",
                  foreground="#888", wraplength=320).grid(
            row=9, column=1, columnspan=2, sticky="w", padx=10)

        # AI cleanup toggle
        self.ai_var = tk.BooleanVar(
            value=self.config.get("ai_cleanup", {}).get("enabled", False))
        ttk.Checkbutton(
            frame,
            text="AI cleanup via Claude (fixes grammar/filler; needs "
                 "ANTHROPIC_API_KEY)",
            variable=self.ai_var,
        ).grid(row=10, column=0, columnspan=3, sticky="w", **pad)

        self.save_btn = ttk.Button(frame, text="Save & Apply",
                                   command=self._save)
        self.save_btn.grid(row=11, column=0, columnspan=3, pady=(10, 2))

        # Update notice — populated by the background check when a newer
        # GitHub release exists; clicking opens the release page.
        self._update_url = None
        self.update_var = tk.StringVar(value="")
        update_lbl = ttk.Label(frame, textvariable=self.update_var,
                               foreground="#0a58ca", cursor="hand2")
        update_lbl.grid(row=12, column=0, columnspan=3, pady=(0, 2))
        update_lbl.bind("<Button-1>", self._open_update)

        ttk.Label(frame, text='Commands: "new line", "new paragraph", '
                              '"select all", "scratch that", '
                              '"delete last sentence" — say one alone, '
                              'not mid-sentence',
                  foreground="#888", font=("Segoe UI", 8),
                  wraplength=360).grid(row=13, column=0, columnspan=3,
                                       sticky="w", padx=10, pady=(4, 0))

        # Closing the window hides to the tray; quit from the tray menu.
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

    def _set_status(self, text, transcript=None):
        def apply():
            self.status_var.set(text)
            if transcript is not None:
                self.transcript_var.set(transcript)
        self.root.after(0, apply)

    # ------------------------------------------------------------- updates

    def _check_updates_async(self):
        def worker():
            try:
                result = check_for_update(VERSION)
            except Exception:
                return  # offline, GitHub unreachable, etc. — stay quiet
            if not result:
                return
            latest, url = result
            self._update_url = url
            self.root.after(0, lambda: self.update_var.set(
                f"Update v{latest} available — click to download"))
            try:
                self.tray.notify(f"Version {latest} is available.",
                                 "WhisperFlow Local update")
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _open_update(self, _event=None):
        if self._update_url:
            webbrowser.open(self._update_url)

    # ---------------------------------------------------------------- tray

    def _start_tray(self):
        self.tray = pystray.Icon(
            "WhisperFlowLocal", TRAY_ICONS["idle"], "WhisperFlow Local",
            menu=pystray.Menu(
                pystray.MenuItem("Show settings", self._tray_show,
                                 default=True),
                pystray.MenuItem("Quit", self._tray_quit),
            ),
        )
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _set_tray(self, state: str, title: str = None):
        try:
            self.tray.icon = TRAY_ICONS[state]
            self.tray.title = title or f"WhisperFlow Local — {state}"
        except Exception:
            pass

    def _hide_to_tray(self):
        self.root.withdraw()
        try:
            self.tray.notify("Still running — hold your hotkey to dictate. "
                             "Right-click the tray dot to quit.",
                             "WhisperFlow Local")
        except Exception:
            pass

    def _tray_show(self, *_args):
        self.root.after(0, lambda: (self.root.deiconify(), self.root.lift()))

    def _tray_quit(self, *_args):
        self.root.after(0, self._quit)

    # -------------------------------------------------------------- engine

    def _load_model_async(self):
        wanted = self.config.get("model_size", "base.en")
        if wanted == self._loaded_model:
            return
        self._set_status(f"Loading model '{wanted}'...")
        self.save_btn.config(state="disabled")

        def worker():
            try:
                self.transcriber = Transcriber(
                    model_size=wanted,
                    device=self.config.get("device", "cpu"),
                    compute_type=self.config.get("compute_type", "int8"),
                )
                self._loaded_model = wanted
                key = self.config.get("hotkey", "f8").upper()
                mode = "Hold" if self.config.get("hold_to_talk", True) else "Press"
                self._set_status(f"Ready — {mode} [{key}] to dictate")
            except Exception as exc:
                self._set_status(f"Model failed to load: {exc}")
            finally:
                self.root.after(0, lambda: self.save_btn.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _init_ai_cleanup(self):
        ai_cfg = self.config.get("ai_cleanup", {})
        if ai_cfg.get("enabled"):
            try:
                self.ai_formatter = AIFormatter(
                    model=ai_cfg.get("model", "claude-opus-4-8"))
            except Exception:
                self.ai_formatter = None

    def _resolve_device(self):
        name = self.config.get("input_device")
        if not name:
            return None
        for idx, dev_name in list_input_devices():
            if dev_name == name:
                return idx
        return None  # device unplugged — fall back to system default

    # ------------------------------------------------------------- hotkeys

    def _register_hotkey(self):
        for hook in self._hooks:
            try:
                keyboard.unhook(hook)
            except Exception:
                pass
        self._hooks = []
        key = self.config.get("hotkey", "f8")
        if self.config.get("hold_to_talk", True):
            self._hooks.append(
                keyboard.on_press_key(key, self._on_press, suppress=True))
            self._hooks.append(
                keyboard.on_release_key(key, self._on_release, suppress=True))
        else:
            self._hooks.append(
                keyboard.on_press_key(key, self._on_toggle, suppress=True))

    def _capture_hotkey(self):
        self.capture_btn.config(text="Press a key...", state="disabled")

        def worker():
            key = keyboard.read_key(suppress=False)
            def apply():
                self.hotkey_var.set(key)
                self.capture_btn.config(text="Set...", state="normal")
            self.root.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _lang_code_for_display(self, display: str):
        if display in _LANG_DISPLAY_TO_CODE:
            return _LANG_DISPLAY_TO_CODE[display]
        return None if display == "Auto-detect" else display

    def _on_language_change(self, _event=None):
        lang_code = self._lang_code_for_display(self.lang_var.get())
        model = self.model_var.get()
        if model.endswith(".en") and lang_code != "en":
            multilingual = model[:-3]
            if multilingual in MODEL_CHOICES:
                self.model_var.set(multilingual)
                self.lang_note_var.set(f"switched model to '{multilingual}'")
            else:
                self.lang_note_var.set(".en models are English-only")
        else:
            self.lang_note_var.set("")

    def _transcribe_args(self):
        vocab = self.config.get("vocabulary") or []
        return self.config.get("language"), (", ".join(vocab) if vocab else None)

    # ------------------------------------------------------- push-to-talk
    # The keyboard hooks fire on the hook thread, but WASAPI streams can
    # only be opened from a COM-initialized thread (opening a specific mic
    # from the hook thread fails with AUDCLNT_E_UNSUPPORTED_FORMAT). So the
    # hook callbacks just forward to the Tk main thread, which PortAudio
    # initialized at import time. root.after preserves press/release order.

    def _on_press(self, _event=None):
        self.root.after(0, self._start_recording)

    def _on_release(self, _event=None):
        self.root.after(0, self._stop_recording)

    def _on_toggle(self, _event=None):
        def toggle():
            if self.recorder.is_recording:
                self._stop_recording()
            else:
                self._start_recording()
        self.root.after(0, toggle)

    def _start_recording(self):
        if self.recorder.is_recording or self._busy or self.transcriber is None:
            return
        try:
            self.recorder.start(device=self._resolve_device())
        except Exception as exc:
            log_error("mic open failed")
            self._set_status(f"Mic error: {exc}")
            return
        _beep(880)
        self._set_tray("rec", "WhisperFlow Local — RECORDING")
        self._set_status("Recording... (release to transcribe)")
        threading.Thread(target=self._partial_loop, daemon=True).start()

    def _partial_loop(self):
        """While the hotkey is held, periodically re-transcribe the audio
        captured so far and show it as a live preview (beam_size=1 for
        speed). The final pass after release re-transcribes at full
        quality, so this only needs to be fast, not perfect."""
        while self.recorder.is_recording:
            time.sleep(PARTIAL_INTERVAL)
            if not self.recorder.is_recording or self.transcriber is None:
                break
            audio = self.recorder.peek()
            if audio.size < int(MIN_PARTIAL_AUDIO * 16000):
                continue
            language, prompt = self._transcribe_args()
            try:
                text = self.transcriber.transcribe(
                    audio, language=language, initial_prompt=prompt,
                    beam_size=1)
            except Exception:
                continue
            if text and self.recorder.is_recording:
                text = to_simplified(text)
                self.root.after(
                    0, lambda t=text: self.transcript_var.set(f"… {t}"))

    def _stop_recording(self):
        if not self.recorder.is_recording:
            return
        audio = self.recorder.stop()
        _beep(660)
        self._set_tray("busy", "WhisperFlow Local — transcribing")
        self._busy = True
        threading.Thread(target=self._process, args=(audio,),
                         daemon=True).start()

    def _process(self, audio):
        try:
            self._set_status("Transcribing...")
            language, prompt = self._transcribe_args()
            raw_text = self.transcriber.transcribe(
                audio, language=language, initial_prompt=prompt)
            if not raw_text:
                self._ready_status(transcript="(no speech detected)")
                return

            action = detect_action(raw_text)
            if action == "discard":
                self._ready_status(transcript="(discarded)")
                return
            if action == "select_all":
                keyboard.send("ctrl+a")
                self._ready_status(transcript="(select all)")
                return
            if action == "delete_last_sentence":
                self._delete_last_sentence()
                self._ready_status(transcript="(deleted last sentence)")
                return

            text = basic_format(raw_text)
            learned_note = ""
            if self.ai_formatter is not None:
                cleaned = self.ai_formatter.cleanup(text)
                candidates = suggest_new_vocab(text, cleaned)
                added = self._learn_vocabulary(candidates) if candidates else []
                if added:
                    learned_note = f"  [learned: {', '.join(added)}]"
                text = cleaned
            inject(text, mode=self.config.get("paste_mode", "paste"))
            self._last_injected_text = text
            self._ready_status(transcript=text + learned_note)
        except Exception as exc:
            log_error("processing failed")
            self._set_status(f"Error: {exc}")
        finally:
            self._busy = False

    def _delete_last_sentence(self):
        """Backspace out the last sentence of the most recent dictation.
        Only reliable if the cursor hasn't moved since that paste."""
        prev = self._last_injected_text
        if not prev:
            return
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", prev.strip()) if s]
        if not sentences:
            return
        sentences.pop()
        remaining = " ".join(sentences)
        delete_count = len(prev) - len(remaining)
        for _ in range(delete_count):
            keyboard.send("backspace")
            time.sleep(0.004)
        self._last_injected_text = remaining

    def _learn_vocabulary(self, new_words: list) -> list:
        """Persist newly-suggested vocabulary words and reflect them in
        the UI. Returns only the words that were actually new."""
        vocab = self.config.get("vocabulary") or []
        existing_lower = {w.lower() for w in vocab}
        added = [w for w in new_words if w.lower() not in existing_lower]
        if not added:
            return []
        vocab = (vocab + added)[-200:]  # cap growth
        self.config["vocabulary"] = vocab
        CONFIG_PATH.write_text(
            json.dumps(self.config, indent=2), encoding="utf-8")
        self.root.after(0, lambda: self.vocab_var.set(", ".join(vocab)))
        return added

    def _ready_status(self, transcript=None):
        key = self.config.get("hotkey", "f8").upper()
        mode = "Hold" if self.config.get("hold_to_talk", True) else "Press"
        self._set_tray("idle", f"WhisperFlow Local — {mode} [{key}]")
        self._set_status(f"Ready — {mode} [{key}] to dictate", transcript)

    # ---------------------------------------------------------------- save

    def _save(self):
        self._on_language_change()  # enforce the .en/language pairing once more
        mic = self.mic_var.get()
        self.config["input_device"] = None if mic == DEFAULT_MIC_LABEL else mic
        self.config["hotkey"] = self.hotkey_var.get() or "f8"
        self.config["hold_to_talk"] = self.hold_var.get()
        self.config["model_size"] = self.model_var.get()
        self.config["language"] = self._lang_code_for_display(self.lang_var.get())
        self.config["vocabulary"] = [
            w.strip() for w in self.vocab_var.get().split(",") if w.strip()]
        self.config.setdefault("ai_cleanup", {})
        self.config["ai_cleanup"]["enabled"] = self.ai_var.get()
        self.config["ai_cleanup"].setdefault("model", "claude-haiku-4-5")
        CONFIG_PATH.write_text(
            json.dumps(self.config, indent=2), encoding="utf-8")
        self._register_hotkey()
        self.ai_formatter = None
        self._init_ai_cleanup()
        if self.ai_var.get() and self.ai_formatter is None:
            self._set_status("AI cleanup enabled but no API key found — "
                             "dictation will paste raw text")
        else:
            self._ready_status()
        self._load_model_async()  # no-op unless the model changed

    def _quit(self):
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self.root.destroy()


def acquire_single_instance():
    """Bind a localhost port as a cross-process lock; a second launch fails."""
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        return sock
    except OSError:
        return None


def main():
    lock = acquire_single_instance()
    if lock is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "WhisperFlow Local",
            "WhisperFlow Local is already running.\n"
            "Look for its window in the taskbar.")
        return 0

    if not CONFIG_PATH.exists():  # fresh install — seed from the example
        example = ASSET_DIR / "config.example.json"
        CONFIG_PATH.write_text(example.read_text(encoding="utf-8"),
                               encoding="utf-8")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    root = tk.Tk()
    try:
        App(root, config)
        root.mainloop()
    except Exception as exc:
        messagebox.showerror("WhisperFlow Local", f"Fatal error:\n{exc}")
        raise
    finally:
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
