"""The languages a user can turn on, shared by the app and the installer.

Stdlib-only on purpose: scripts/configure.py imports this before setup has
installed any dependencies.

Auto-detect only ever chooses between the languages in config["languages"].
Whisper's own detector ranks all 99, and on short or noisy speech its
runners-up are junk like Welsh or Nynorsk rather than a plausible second
guess — so each user picks the handful they actually speak.
"""

# Whisper code -> display name, in menu order. Any Whisper language works in
# principle; these are the ones offered.
LANGUAGE_NAMES = {
    "en": "English",
    "zh": "Chinese",
    "ms": "Malay",
    "ta": "Tamil",
    "id": "Indonesian",
    "th": "Thai",
    "vi": "Vietnamese",
    "tl": "Tagalog",
    "ja": "Japanese",
    "ko": "Korean",
    "hi": "Hindi",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ru": "Russian",
    "ar": "Arabic",
}

DEFAULT_LANGUAGES = ["en", "zh"]

# Short labels for the status line ("heard 中文").
SHORT_LABELS = {"zh": "中文"}


def configured_languages(config: dict) -> list[str]:
    """The user's enabled languages, unknown codes dropped, never empty."""
    codes = [c for c in (config.get("languages") or []) if c in LANGUAGE_NAMES]
    return codes or list(DEFAULT_LANGUAGES)


def short_label(code: str) -> str:
    return SHORT_LABELS.get(code, code.upper())
