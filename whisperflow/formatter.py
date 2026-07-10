"""Formatting layer: turn raw transcript text into polished dictation.

Two tiers, mirroring Wispr Flow's AI-formatting stage:
  1. Rule-based (always on, fully local): spoken commands like
     "new line" / "new paragraph", whitespace cleanup, capitalization.
  2. Optional AI cleanup via the Anthropic API — fixes grammar and removes
     self-corrections/filler. Off by default so the app stays 100% local.
"""

import re

_VOICE_COMMANDS = [
    (re.compile(r"[.,]?\s*\bnew paragraph\b[.,]?\s*", re.IGNORECASE), "\n\n"),
    (re.compile(r"[.,]?\s*\bnew line\b[.,]?\s*", re.IGNORECASE), "\n"),
]

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
