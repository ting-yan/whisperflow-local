# WhisperFlow Local

A local-first clone of Wispr Flow's architecture: system-wide push-to-talk
dictation for Windows. Hold a hotkey, speak, release — the transcript is
cleaned up and pasted into whatever app has focus. Speech never leaves your
machine.

**Features**

- Push-to-talk (or press-to-toggle) dictation into any app
- 100% local speech recognition (Whisper via `faster-whisper`) — runs on an
  NVIDIA GPU when one is usable (~5x faster), otherwise on the CPU
- **Live partial transcript** while you're still talking, refined into the
  final result the moment you release the key
- Settings window: pick your microphone, hotkey, model size, and language
- **Pick your languages at install, with auto-detect** — choose the ones you
  speak (English, Chinese, Malay, Tamil, and 15 more); the app auto-detects
  between exactly those, or you pin one (multilingual models only — `.en`
  models are English-only and setup/the app switch you off them automatically)
- **Singlish mode** — biases the decoder toward Singlish spelling (`lah`,
  `leh`, `shiok`, `makan`, `paiseh`, `jialat`) instead of the English words
  that sound like them
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

Setup asks two questions:

- **Which languages you'll dictate in** — type menu numbers or codes, e.g.
  `1,2` or `en,zh,ms`. Press Enter to keep the current set (English +
  Chinese on a fresh install).
- **GPU or CPU** — only asked if it finds an NVIDIA card. GPU is ~5x faster
  but downloads NVIDIA's CUDA runtime (~700 MB, one-time); CPU needs nothing
  extra.

Then it installs Python 3.12 if you don't have it, installs dependencies,
creates Desktop + Startup shortcuts, and launches the app. First launch
downloads the speech model (~75 MB); after that it's fully offline.

Re-run `setup.bat` any time to change either answer — your other settings
(vocabulary, hotkey, model) are kept.

**AMD and Intel machines:** the speech engine (CTranslate2) only supports
NVIDIA GPUs, so AMD Radeon and Intel graphics run on the CPU. That works on
any modern x86 processor, AMD Ryzen included — CTranslate2 picks oneDNN
instead of Intel MKL on non-Intel CPUs automatically. `base`/`small` are the
sizes to use on CPU.

**Standalone exe** (from [Releases](../../releases)): no setup, CPU only,
English + Chinese by default — change them with **Languages...** in the app.

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
| Language | Auto-detect between your enabled languages, or pin one of them (see below). **Languages...** changes which are enabled (also asked at install). Picking anything but English auto-switches you off a `.en` model, since those can't recognize other languages at all |
| Vocabulary | Comma-separated words Whisper should favor (names, jargon). Auto-grows: when AI cleanup fixes a name Whisper misheard, it's added here automatically (capped at 200 entries) |
| Singlish mode | Adds Singlish particles and loanwords to the prompt when the utterance is English. See below |
| AI cleanup | Sends transcripts to Claude (`claude-haiku-4-5`) for grammar/filler fixes. Needs `ANTHROPIC_API_KEY`; no longer fully local when enabled. Also powers the vocabulary auto-learning above |

Config-file-only options: `paste_mode` (`"type"` simulates keystrokes for
apps that block paste), and `device`/`compute_type` — see below.

### GPU

`"device": "auto"` (the default) uses the NVIDIA GPU when it works and falls
back to the CPU when it doesn't; `"cuda"` and `"cpu"` force one. Leave
`"compute_type": null` to get the right default per device (`float16` on GPU,
`int8` on CPU). The status line and tray tooltip say which one you got.

Setup writes `"auto"` if you choose the GPU and `"cpu"` if you don't (or
have no NVIDIA card). The GPU path needs the CUDA 12 runtime — setup installs
it when you choose the GPU, or by hand:

```powershell
pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9"
```

These wheels drop their DLLs in `site-packages/nvidia/*/bin`, which is on no
search path, so `transcriber.py` prepends those directories to `PATH` at
import. Without that you get `Library cublas64_12.dll is not found` — and not
at load time: `WhisperModel(device="cuda")` constructs fine and only fails on
the first encode. That's also why the model is warmed up with a real encode
during load, so a broken GPU falls back before you dictate rather than during.

Measured on an RTX 2060 (6 GB), `small`, final pass at beam 5:

| Audio | CPU `int8` | GPU `float16` |
|-------|-----------|---------------|
| 5s | 2.0s | 0.23s |
| 10s | 2.2s | 0.42s |
| 21s | 3.1s | 0.68s |

The GPU also makes bigger models cheaper than `small` on CPU is today:
`medium` ≈ 1.7s and `large-v3` ≈ 2.4s on 21s of audio. Model load costs
~2s (`small`) to ~5s (`large-v3`), once, at startup.

### Language detection

Auto-detect chooses **only between the languages in `config["languages"]`**
(picked at install). Whisper's own detector ranks all 99 languages and picks
the top one; on short or noisy speech its runners-up are junk like Welsh or
Nynorsk rather than a plausible second guess, and if one of those wins, the
decoder switches into a language you aren't speaking and the whole utterance
is lost. Scoring only your languages limits a misdetection to one of them —
which is also why it's worth enabling only the ones you actually speak.

Detection runs once per utterance (`Transcriber.reset_detection()` on key-down)
rather than on every live-partial pass — one encoder pass, ~80ms on GPU, and
the preview can't flip script mid-sentence. Pinning a language in the picker
skips it entirely. The status line shows what it settled on (`· heard 中文`).

Code-switching is why, when English is enabled, any other language needs a
**1.5x lead** over it before auto-detect switches (`DETECT_NON_EN_MARGIN`). An English sentence with a few
Mandarin words in it scored `en=0.469` / `zh=0.523` in testing — a plain
argmax would decode the whole thing as Chinese and lose the English. With the
margin it stays in English, and Whisper still writes the Chinese span in
Chinese characters. Genuine Chinese (`zh=0.998` vs `en=0.001`) clears the
margin easily. The margin was only measured on English/Chinese; it applies to
the other languages on the same reasoning, untested.

The menu offered at install lives in `LANGUAGE_NAMES` in
`whisperflow/languages.py`; any Whisper language code can be added there.

### Singlish

Singlish is not a language Whisper knows — there's no language token for it,
and it is recognized as English. What the toggle does is put Singlish
particles and loanwords (`SINGLISH_TERMS` in `whisperflow/transcriber.py`)
into the initial prompt, which biases the decoder toward those spellings.
The terms are only added when the utterance is English, so Chinese dictation
isn't polluted with them.

Measured on `medium`, same clips, toggle off → on:

| Off | On |
|-----|-----|
| this one damn **Shiok Law** | this one damn **shiok lah!** |
| you very **kiyosusieh** … he already booked **Leo** | you very **kiasu sia** … he already booked **liao** |
| **Ayo, Sogeolet** … don't want to **tae an** already | **Aiyo, sojialat** … don't want to **tahan** already |

The prompt is deliberately written as prose with capitals and full stops.
Whisper copies the style of its prompt: an earlier version that passed a bare
lowercase word list fixed the vocabulary but made the whole transcript come
back lowercase and unpunctuated.

Limits worth knowing: this is prompt biasing, not a Singlish model. Words the
model has a weak prior on still come out wrong (`lor` → "lore", `makan` →
"makin'") no matter what the prompt says, and the numbers above come from
text-to-speech readings of Singlish rather than a real speaker.

Chinese output is normalized to Simplified regardless of what Whisper emits
(`to_simplified()` in `formatter.py`); the `zh` tag doesn't distinguish
Simplified from Traditional.

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
  On a GPU, `small` is ~0.2–0.7s and even `large-v3` beats `small` on CPU.

## License

MIT — see [LICENSE](LICENSE). Third-party dependency licenses (including one
LGPL component) are listed in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
