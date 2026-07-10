"""WhisperFlow Local — local push-to-talk dictation with a settings UI.

Hold the hotkey (default F8), speak, release. The transcript is formatted
and pasted into whatever window has focus. The window lets you pick the
microphone, change the hotkey, switch models, and toggle hold-vs-toggle mode.

Run with:  pythonw app.py   (no console)  or  python app.py  (with console)
"""

import json
import socket
import sys
import threading
import time
from pathlib import Path

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
from whisperflow.formatter import basic_format, AIFormatter
from whisperflow.injector import inject

CONFIG_PATH = Path(__file__).parent / "config.json"
LOG_PATH = Path(__file__).parent / "whisperflow.log"
MODEL_CHOICES = ["tiny.en", "base.en", "small.en", "medium", "large-v3"]


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

        self._build_ui()
        self._start_tray()
        self._register_hotkey()
        self._load_model_async()
        self._init_ai_cleanup()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        self.root.title("WhisperFlow Local")
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

        # Custom vocabulary
        ttk.Label(frame, text="Vocabulary:").grid(row=7, column=0,
                                                  sticky="w", **pad)
        self.vocab_var = tk.StringVar(
            value=", ".join(self.config.get("vocabulary") or []))
        ttk.Entry(frame, textvariable=self.vocab_var,
                  width=37).grid(row=7, column=1, columnspan=2,
                                 sticky="w", **pad)
        ttk.Label(frame, text="Comma-separated words Whisper should favor "
                              "(names, jargon)",
                  foreground="#888").grid(row=8, column=1, columnspan=2,
                                          sticky="w", padx=10)

        # AI cleanup toggle
        self.ai_var = tk.BooleanVar(
            value=self.config.get("ai_cleanup", {}).get("enabled", False))
        ttk.Checkbutton(
            frame,
            text="AI cleanup via Claude (fixes grammar/filler; needs "
                 "ANTHROPIC_API_KEY)",
            variable=self.ai_var,
        ).grid(row=9, column=0, columnspan=3, sticky="w", **pad)

        self.save_btn = ttk.Button(frame, text="Save & Apply",
                                   command=self._save)
        self.save_btn.grid(row=10, column=0, columnspan=3, pady=(10, 2))

        # Closing the window hides to the tray; quit from the tray menu.
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

    def _set_status(self, text, transcript=None):
        def apply():
            self.status_var.set(text)
            if transcript is not None:
                self.transcript_var.set(transcript)
        self.root.after(0, apply)

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
            vocab = self.config.get("vocabulary") or []
            text = self.transcriber.transcribe(
                audio,
                language=self.config.get("language"),
                initial_prompt=", ".join(vocab) if vocab else None)
            if not text:
                self._ready_status(transcript="(no speech detected)")
                return
            text = basic_format(text)
            if self.ai_formatter is not None:
                text = self.ai_formatter.cleanup(text)
            inject(text, mode=self.config.get("paste_mode", "paste"))
            self._ready_status(transcript=text)
        except Exception as exc:
            self._set_status(f"Error: {exc}")
        finally:
            self._busy = False

    def _ready_status(self, transcript=None):
        key = self.config.get("hotkey", "f8").upper()
        mode = "Hold" if self.config.get("hold_to_talk", True) else "Press"
        self._set_tray("idle", f"WhisperFlow Local — {mode} [{key}]")
        self._set_status(f"Ready — {mode} [{key}] to dictate", transcript)

    # ---------------------------------------------------------------- save

    def _save(self):
        mic = self.mic_var.get()
        self.config["input_device"] = None if mic == DEFAULT_MIC_LABEL else mic
        self.config["hotkey"] = self.hotkey_var.get() or "f8"
        self.config["hold_to_talk"] = self.hold_var.get()
        self.config["model_size"] = self.model_var.get()
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
        example = Path(__file__).parent / "config.example.json"
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
