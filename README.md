# WhisperFlow Local

A local-first clone of Wispr Flow's architecture: system-wide push-to-talk
dictation for Windows. Hold a hotkey, speak, release — the transcript is
cleaned up and pasted into whatever app has focus. Speech never leaves your
machine.

**Features**

- Push-to-talk (or press-to-toggle) dictation into any app
- 100% local speech recognition (Whisper via `faster-whisper`, CPU-friendly)
- **Live partial transcript** while you're still talking, refined into the
  final result the moment you release the key
- Settings window: pick your microphone, hotkey, model size, and language
- **Multi-language / auto-detect** — ~13 languages in the picker, or let
  Whisper detect automatically (multilingual models only — `.en` models are
  English-only and the app switches you off them automatically)
- System-tray icon with live status (blue = ready, red = recording, orange = transcribing)
- Custom vocabulary so your names/jargon come out spelled right — **grows on
  its own** when AI cleanup corrects a name Whisper misheard
- Voice commands: "new line", "new paragraph", "select all", "scratch that",
  "delete last sentence"
- Optional AI cleanup via the Anthropic API (grammar, filler removal) — off by default
- Auto-starts with Windows (Startup shortcut created by setup)

## Install

1. [Download the ZIP](../../archive/refs/heads/main.zip) (or `git clone` this repo) and extract it somewhere permanent
2. Double-click **`setup.bat`**

That's it — setup installs Python 3.12 if you don't have it, installs
dependencies, creates Desktop + Startup shortcuts, and launches the app.
First launch downloads the speech model (~75 MB); after that it's fully
offline.

## Usage

- **Hold F8**, speak, release. High beep = recording, low beep = processing.
  A rough live transcript appears in the window while you talk; the accurate
  final version pastes at your cursor once you release, and your clipboard is
  restored afterwards.
- Closing the settings window hides the app to the **system tray** — it keeps
  running. Left-click the tray dot for settings, right-click → Quit to exit.

### Voice commands

Say one of these **alone** — as the entire thing you dictate, not embedded in
a sentence — and it triggers an action instead of being pasted as text:

| Say | Does |
|-----|------|
| "new line" / "new paragraph" | Insert a line/paragraph break (works mid-sentence too) |
| "select all" | Sends Ctrl+A in the focused app |
| "scratch that" / "never mind" / "cancel that" | Discards the current dictation — nothing is pasted |
| "delete last sentence" / "undo that" | Backspaces out the last sentence you dictated |

`delete last sentence` only works if the cursor hasn't moved since your last
dictation landed — it deletes by character count from where the paste ended,
so clicking elsewhere or typing in between will delete the wrong text.

## Architecture (mapped to Wispr Flow)

| Wispr Flow layer        | Local equivalent                          | File |
|-------------------------|-------------------------------------------|------|
| Global hotkey trigger   | `keyboard` hook, hold-to-talk             | `app.py` |
| Mic capture             | `sounddevice` stream, resampled to 16 kHz | `whisperflow/recorder.py` |
| Cloud ASR               | **local** Whisper via `faster-whisper`    | `whisperflow/transcriber.py` |
| AI formatting           | rules + vocabulary + optional Claude polish | `whisperflow/formatter.py` |
| Text insertion          | clipboard paste (Ctrl+V) with clipboard restore | `whisperflow/injector.py` |

Flow: `hold hotkey → record mic (live partial preview every ~1.2s) → release → Whisper transcribe (full quality) → format/commands/learning → paste`

## Settings

Everything is in the app window (saved to `config.json`, created from
`config.example.json` on first run):

| Setting | Notes |
|---------|-------|
| Microphone | Any input device, or system default |
| Hotkey | Click Set..., press a key |
| Hold to talk | Unchecked = press once to start, again to stop |
| Model | `tiny.en`/`tiny` (fastest) → `large-v3` (best). `base.en`/`small.en` are the sweet spots on CPU. `.en` = English-only, bare name = multilingual |
| Language | Auto-detect or ~13 languages. Picking anything but English auto-switches you off a `.en` model, since those can't recognize other languages at all |
| Vocabulary | Comma-separated words Whisper should favor (names, jargon). Auto-grows: when AI cleanup fixes a name Whisper misheard, it's added here automatically (capped at 200 entries) |
| AI cleanup | Sends transcripts to Claude (`claude-haiku-4-5`) for grammar/filler fixes. Needs `ANTHROPIC_API_KEY`; no longer fully local when enabled. Also powers the vocabulary auto-learning above |

Config-file-only options: `paste_mode` (`"type"` simulates keystrokes for
apps that block paste), `device`/`compute_type` (`"cuda"`/`"float16"` for
NVIDIA GPUs with the CUDA 12 runtime:
`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`).

## Development

```powershell
python -m pip install -r requirements.txt
python scripts/smoke_test.py   # end-to-end pipeline test with synthetic speech
python app.py                  # run with a console for debugging
```

Errors are also appended to `whisperflow.log` (the app normally runs
windowless via `pythonw`).

## Notes

- Windows-only as shipped (`winsound`, WASAPI handling, shortcuts).
- Latency on CPU: `base.en` ≈ 0.5–1.5s per sentence, `small.en` ≈ 2–3s.

## License

MIT — see [LICENSE](LICENSE). Third-party dependency licenses (including one
LGPL component) are listed in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
