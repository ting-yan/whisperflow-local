"""PyInstaller runtime hook: stand in for PyAV in the exe build.

faster-whisper imports `av` at module level, but only uses it to decode
audio *files* (decode_audio). The app always passes a numpy array, so PyAV
is never called. Excluding it from the bundle drops FFmpeg and the codec
DLLs it carries (x264/x265 among them: GPL and patent-encumbered video
encoders this app has no use for).

If anything ever does reach for PyAV, it fails loudly instead of silently.
"""

import sys
import types

if "av" not in sys.modules:
    _av = types.ModuleType("av")

    def __getattr__(name):
        raise ImportError(
            f"av.{name}: PyAV is not bundled in this build — "
            "only in-memory audio is supported")

    _av.__getattr__ = __getattr__
    sys.modules["av"] = _av
