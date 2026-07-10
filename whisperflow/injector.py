"""Injection layer: deliver text into the focused window.

Default mode saves the clipboard, pastes via Ctrl+V, then restores the
clipboard — fast and reliable for any text field. "type" mode simulates
keystrokes instead, for apps that block paste.
"""

import time

import keyboard
import pyperclip


def inject(text: str, mode: str = "paste"):
    if not text:
        return
    if mode == "type":
        keyboard.write(text, delay=0.005)
        return

    saved = None
    try:
        saved = pyperclip.paste()
    except Exception:
        pass

    pyperclip.copy(text)
    time.sleep(0.05)  # let the clipboard settle before pasting
    keyboard.send("ctrl+v")

    if saved is not None:
        time.sleep(0.3)  # target app must read the clipboard before restore
        try:
            pyperclip.copy(saved)
        except Exception:
            pass
