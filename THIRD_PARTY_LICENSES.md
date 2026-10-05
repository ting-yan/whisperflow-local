# Third-Party Licenses

WhisperFlow Local's own code is MIT-licensed (see [LICENSE](LICENSE)). It is
distributed two ways, and they differ in what this project redistributes:

- **Source install (`setup.bat`)**: this repo contains only WhisperFlow's own
  code. `pip` downloads every dependency from PyPI onto the user's machine,
  under that package's own license.
- **Standalone exe** (GitHub Releases): the dependencies below are bundled
  and redistributed with the app. **The full license text of every bundled
  component ships in the `licenses/` folder next to `WhisperFlowLocal.exe`**,
  indexed in `licenses/INDEX.txt`. `WhisperFlowLocal.spec` generates both at
  build time from the installed packages, plus the texts in `licenses-extra/`
  for components that don't carry their own.

## Direct dependencies

| Package | License | Used for | In exe |
|---|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | speech-to-text engine | yes |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT | faster-whisper's inference backend | yes |
| [onnxruntime](https://github.com/microsoft/onnxruntime) | MIT (+ `ThirdPartyNotices.txt`) | faster-whisper's voice-activity filter | yes |
| [tokenizers](https://github.com/huggingface/tokenizers) | Apache-2.0 | text tokenization | yes |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | Apache-2.0 | model downloading | yes |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | MIT | microphone capture | yes |
| [PortAudio](https://www.portaudio.com) | MIT-style | audio I/O library inside sounddevice | yes |
| [keyboard](https://github.com/boppreh/keyboard) | MIT | global hotkey listener | yes |
| [pyperclip](https://github.com/asweigart/pyperclip) | BSD | clipboard paste | yes |
| [NumPy](https://numpy.org) | BSD-3-Clause (+ bundled notices) | audio array processing | yes |
| [Pillow](https://python-pillow.github.io) | MIT-CMU | tray icon rendering | yes |
| [pystray](https://github.com/moses-palmer/pystray) | **LGPL-3.0-or-later** | system tray icon | yes, as `.py` files |
| [opencc-python-reimplemented](https://github.com/yichen0831/opencc-python) | Apache-2.0 | normalizing Chinese to Simplified | yes |
| [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) | MIT | optional AI cleanup (Claude) | yes |
| [PyAV](https://github.com/PyAV-Org/PyAV) (+ FFmpeg) | BSD-3-Clause; FFmpeg LGPL/GPL | pulled in by faster-whisper; unused | **no**, see below |
| [PyInstaller](https://pyinstaller.org) | GPL-2.0-or-later, **with a bundling exception** | builds the exe | build tool only |

The indirect dependencies bundled in the exe (via huggingface_hub, anthropic
and onnxruntime) are all permissive: MIT, BSD, Apache-2.0 and PSF-2.0, plus
**MPL-2.0** for `certifi` and `tqdm` (see below). The exact list with
versions is in `licenses/INDEX.txt` in the exe build.

## Native components in the exe

| Component | License | Text in `licenses/` |
|---|---|---|
| Python 3.12 runtime | PSF-2.0 | `Python-LICENSE.txt` |
| Libraries built into Python: OpenSSL (Apache-2.0), libffi, expat, libmpdec, bzip2, zlib, Tcl/Tk, SQLite (public domain) | various permissive | `Python-LICENSE.txt` and `Python-incorporated-software.txt` |
| Microsoft Visual C++ runtime (`vcruntime140.dll`, `msvcp140.dll`) | Microsoft redistributable | shipped as part of Python |
| Intel OpenMP runtime (`libiomp5md.dll`, inside the CTranslate2 wheel) | Intel redistributable / BSD-3-Clause | `Intel-OpenMP-NOTICE.txt` |

## Deliberately left out of the exe

These come with dependency wheels, but `WhisperFlowLocal.spec` excludes
them. The app never uses them, and their license terms make them things it
shouldn't redistribute:

- **PyAV and FFmpeg**, including the x264/x265 video encoders, which are
  GPL-licensed and patent-encumbered. faster-whisper only uses PyAV to decode
  audio *files*, and the app always passes in-memory audio. A runtime hook
  (`scripts/pyi_rth_no_av.py`) stands in for the module.
- **NVIDIA cuDNN** (`cudnn64_9.dll`, proprietary), which ships inside the
  CTranslate2 wheel. The exe is CPU-only, and cuDNN is useless without
  cuBLAS anyway.
- **PortAudio's ASIO build** (`libportaudio64bit-asio.dll`), built with
  Steinberg's ASIO SDK. sounddevice only loads it when `SD_ENABLE_ASIO` is
  set.

Exe builds up to and including the first v1.4.0 upload did include these.
The rebuilt v1.4.0 zip and later builds don't.

## Notes

**pystray (LGPL-3.0-or-later).** This is the only copyleft library in the
exe. LGPL allows use in closed-source and commercial applications, provided
the license text ships with it (`licenses/pystray/`) and users can replace
the library with their own version. The build collects pystray as plain,
unmodified `.py` files in `_internal/pystray/` rather than inside the
compiled archive, so users can swap it by replacing those files.

**certifi and tqdm (MPL-2.0).** MPL is a file-level copyleft: it applies
only to those packages' own files, which ship unmodified. Their source is
available from [certifi](https://github.com/certifi/python-certifi) and
[tqdm](https://github.com/tqdm/tqdm).

**PyInstaller (GPL-2.0-or-later + exception).** PyInstaller's license has an
explicit exception that lets apps built with it be distributed under any
license, including closed-source or commercial ones. Using it does not place
WhisperFlow Local under the GPL. See
<https://pyinstaller.org/en/stable/license.html>.

**NVIDIA CUDA runtime (GPU, source installs only).** If you choose the GPU
during `setup.bat`, pip downloads `nvidia-cublas-cu12` and `nvidia-cudnn-cu12`
from PyPI onto your machine under NVIDIA's license. This project does not
redistribute them.

**Whisper model weights.** These are not bundled. The app downloads them on
first run from Hugging Face (`Systran/faster-whisper-*`), where they are
licensed MIT, matching OpenAI's original Whisper release.

**Anthropic API (optional AI cleanup).** The `ai_cleanup` feature sends
transcript text to the Anthropic API using the user's own API key. That is
governed by [Anthropic's terms](https://www.anthropic.com/legal/consumer-terms),
not by any package license above. It is off by default.
