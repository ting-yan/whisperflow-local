# Third-Party Licenses

WhisperFlow Local is MIT-licensed (see [LICENSE](LICENSE)). It depends on the
following third-party packages, most bundled directly into the standalone
`.exe` build. Their own licenses continue to apply to their respective code.

| Package | License | Used for |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | speech-to-text engine |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT | faster-whisper's inference backend |
| [tokenizers](https://github.com/huggingface/tokenizers) | Apache-2.0 | text tokenization |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | Apache-2.0 | model downloading |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | MIT | microphone capture |
| [keyboard](https://github.com/boppreh/keyboard) | MIT | global hotkey listener |
| [pyperclip](https://github.com/asweigart/pyperclip) | BSD | clipboard paste |
| [NumPy](https://numpy.org) | BSD-3-Clause | audio array processing |
| [Pillow](https://python-pillow.github.io) | MIT-CMU | tray icon rendering |
| [pystray](https://github.com/moses-palmer/pystray) | **LGPL-3.0-or-later** | system tray icon |
| [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) | MIT | optional AI cleanup (Claude) |
| [PyInstaller](https://pyinstaller.org) | GPL-2.0-or-later, **with a bundling exception** | builds the standalone `.exe` |

## Notes

**pystray (LGPL-3.0-or-later).** This is the only copyleft dependency. LGPL
permits linking into closed-source applications; it requires that the
license text stay available (see below) and that the library component
remain replaceable by the end user. In this build, pystray ships as
unmodified Python bytecode inside the `_internal/` folder next to the
`.exe`, so it can be swapped for a different version without touching the
rest of the app — this satisfies the LGPL's relinking requirement. The full
LGPL-3.0 text is at <https://www.gnu.org/licenses/lgpl-3.0.html>.

**PyInstaller (GPL-2.0-or-later + exception).** PyInstaller's own license
includes an explicit exception permitting apps built with it to be
distributed under any license, including closed-source or commercial ones —
using it to produce this `.exe` does not place WhisperFlow Local under the
GPL. See <https://pyinstaller.org/en/stable/license.html>.

**Whisper model weights.** Not bundled in the `.exe` — downloaded on first
run from Hugging Face (`Systran/faster-whisper-*`). These are MIT-licensed,
matching OpenAI's original Whisper release.

**Anthropic API (optional AI cleanup).** Using the `ai_cleanup` feature sends
transcript text to the Anthropic API and is governed by
[Anthropic's terms of service](https://www.anthropic.com/legal/consumer-terms),
separately from any package license above. The feature is off by default.
