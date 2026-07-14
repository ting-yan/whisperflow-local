"""Capture layer: microphone audio capture.

Whisper wants 16 kHz mono float32, but WASAPI devices (used when the user
picks a specific mic) only open at their native rate — e.g. 48 kHz — and
sometimes only at their native channel count. So we open the stream with
whatever the device accepts and convert to 16 kHz mono on read.
"""

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000


def _to_16k_mono(frames: list, rate: int) -> np.ndarray:
    if not frames:
        return np.zeros(0, dtype=np.float32)
    audio = np.concatenate(frames)
    if audio.ndim > 1:  # downmix stereo to mono
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)
    if rate != SAMPLE_RATE and audio.size:
        target_len = int(audio.size * SAMPLE_RATE / rate)
        audio = np.interp(
            np.linspace(0, audio.size - 1, target_len),
            np.arange(audio.size),
            audio,
        ).astype(np.float32)
    return audio


class Recorder:
    def __init__(self):
        self._frames = []
        self._stream = None
        self._rate = SAMPLE_RATE

    def start(self, device=None):
        """Begin capture. device is a sounddevice index, or None for system default."""
        self._frames = []

        attempts = [(SAMPLE_RATE, 1)]
        if device is not None:
            info = sd.query_devices(device)
            native = int(info["default_samplerate"])
            max_ch = max(1, int(info["max_input_channels"]))
            attempts += [(native, 1), (native, min(2, max_ch))]

        last_exc = None
        for rate, channels in attempts:
            try:
                stream = sd.InputStream(
                    samplerate=rate,
                    channels=channels,
                    dtype="float32",
                    device=device,
                    callback=self._callback,
                )
                stream.start()
                self._stream = stream
                self._rate = rate
                return
            except Exception as exc:
                last_exc = exc
        raise last_exc

    def _callback(self, indata, frames, time_info, status):
        self._frames.append(indata.copy())

    def peek(self) -> np.ndarray:
        """Non-destructively return 16 kHz mono audio captured so far.
        Safe to call mid-recording (used for live partial transcripts) —
        does not stop the stream or clear the buffer."""
        return _to_16k_mono(self._frames[:], self._rate)

    def stop(self) -> np.ndarray:
        """Stop recording; return 16 kHz mono float32 audio."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        audio = _to_16k_mono(self._frames, self._rate)
        self._frames = []
        return audio

    @property
    def is_recording(self) -> bool:
        return self._stream is not None
