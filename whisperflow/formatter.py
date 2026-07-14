"""Formatting layer: turn raw transcript text into polished dictation.

Two tiers, mirroring Wispr Flow's AI-formatting stage:
  1. Rule-based (always on, fully local): spoken commands like
     "new line" / "new paragraph", whitespace cleanup, capitalization.
  2. Optional AI cleanup via the Anthropic API — fixes grammar and removes
     self-corrections/filler. Off by default so the app stays 100% local.
"""

import re

_CJK_RE = re.compile(r"[一-鿿]")  # CJK Unified Ideographs
_opencc_converter = None


def to_simplified(text: str) -> str:
    """Normalize any Chinese in text to Simplified script. Whisper's "zh"
    language tag doesn't distinguish Simplified/Traditional, so its output
    isn't consistently one or the other — this fixes it up afterward.
    No-op (and no OpenCC import cost) when the text has no CJK characters,
    so non-Chinese dictation never pays for it."""
    global _opencc_converter
    if not _CJK_RE.search(text):
        return text
    if _opencc_converter is None:
        from opencc import OpenCC
        _opencc_converter = OpenCC("t2s")
    return _opencc_converter.convert(text)


_VOICE_COMMANDS = [
    (re.compile(r"[.,]?\s*\bnew paragraph\b[.,]?\s*", re.IGNORECASE), "\n\n"),
    (re.compile(r"[.,]?\s*\bnew line\b[.,]?\s*", re.IGNORECASE), "\n"),
]

# Whole-utterance action commands — checked against the ENTIRE dictated
# phrase, never mid-sentence, so ordinary dictation containing these words
# ("select all the applicants") can't misfire as a command.
VOICE_ACTIONS = {
    "select all": "select_all",
    "select everything": "select_all",
    "scratch that": "discard",
    "never mind": "discard",
    "cancel that": "discard",
    "delete last sentence": "delete_last_sentence",
    "delete that sentence": "delete_last_sentence",
    "undo that": "delete_last_sentence",
}


def detect_action(text: str) -> str | None:
    """Return the action name if the whole utterance is a command phrase,
    else None."""
    normalized = text.strip().strip(".,!?").strip().lower()
    return VOICE_ACTIONS.get(normalized)


def suggest_new_vocab(raw: str, cleaned: str) -> list[str]:
    """Words that appear capitalized in AI-cleaned text but nowhere in the
    raw Whisper transcript — likely names/jargon Whisper misheard and
    Claude corrected. Feeds the "learned vocabulary" feature."""
    raw_words = {w.lower() for w in re.findall(r"[A-Za-z']+", raw)}
    seen = set()
    candidates = []
    for word in re.findall(r"[A-Za-z']+", cleaned):
        if len(word) < 3 or not word[0].isupper():
            continue
        low = word.lower()
        if low in raw_words or low in seen:
            continue
        seen.add(low)
        candidates.append(word)
    return candidates


CLEANUP_SYSTEM = (
    "You clean up dictated text. Fix grammar, punctuation, and casing. "
    "Remove filler words (um, uh, you know) and apply self-corrections the "
    "speaker made mid-sentence (e.g. 'meet at 3 no wait 4' becomes 'meet at 4'). "
    "Preserve the speaker's meaning, tone, and wording otherwise. "
    "Return ONLY the cleaned text with no commentary."
)


def basic_format(text: str) -> str:
    for pattern, replacement in _VOICE_COMMANDS:
        text = pattern.sub(replacement, text)
    # Collapse runs of spaces/tabs but keep the newlines the commands inserted.
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n")).strip()
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    text = to_simplified(text)
    return text


class AIFormatter:
    """Optional Claude-powered cleanup. Requires ANTHROPIC_API_KEY."""

    def __init__(self, model: str = "claude-opus-4-8"):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model

    def cleanup(self, text: str) -> str:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=CLEANUP_SYSTEM,
                messages=[{"role": "user", "content": text}],
            )
            for block in response.content:
                if block.type == "text":
                    cleaned = block.text.strip()
                    return cleaned if cleaned else text
            return text
        except Exception as exc:
            # Dictation must never be lost because cleanup failed.
            print(f"  [ai-cleanup failed, using raw text: {exc}]")
            return text
