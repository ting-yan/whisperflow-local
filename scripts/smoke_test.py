"""End-to-end pipeline test without a microphone.

Generates a spoken WAV using Windows' built-in text-to-speech, runs it
through the transcriber + formatter, and checks the words come back.

Run with:  python scripts/smoke_test.py
"""

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from whisperflow.transcriber import Transcriber
from whisperflow.formatter import basic_format

PHRASE = "Hello world. This is a test of local dictation."


def synthesize(text: str, wav_path: str):
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{wav_path}'); "
        f"$s.Speak('{text}'); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def load_wav_as_float32_16k(wav_path: str) -> np.ndarray:
    with wave.open(wav_path, "rb") as w:
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = data.astype(np.float32) / 32768.0
    if rate != 16000:  # crude linear resample is fine for a smoke test
        target_len = int(len(audio) * 16000 / rate)
        audio = np.interp(
            np.linspace(0, len(audio) - 1, target_len),
            np.arange(len(audio)),
            audio,
        ).astype(np.float32)
    return audio


def main():
    wav_path = str(Path(tempfile.gettempdir()) / "whisperflow_smoke.wav")
    print(f"Synthesizing speech: {PHRASE!r}")
    synthesize(PHRASE, wav_path)

    audio = load_wav_as_float32_16k(wav_path)
    print(f"Audio: {audio.size / 16000:.1f}s at 16kHz")

    print("Loading model (downloads on first run)...")
    transcriber = Transcriber(model_size="base.en")

    text = basic_format(transcriber.transcribe(audio, language="en"))
    print(f"Transcript: {text!r}")

    got = text.lower()
    expected = ["hello", "world", "test", "dictation"]
    missing = [w for w in expected if w not in got]
    if missing:
        print(f"FAIL: missing words {missing}")
        return 1
    print("PASS: pipeline works end to end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
