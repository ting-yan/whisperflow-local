"""Installer helper: list the language menu, or write install-time choices
into config.json.

Called by setup.ps1, before and after dependencies are installed, so it
uses the standard library only. Merges into an existing config.json rather
than replacing it, so re-running setup keeps vocabulary, hotkey, etc.

    python scripts/configure.py --list
    python scripts/configure.py --current
    python scripts/configure.py --languages 1,2 --device auto
    python scripts/configure.py --languages en,zh,ms --device cpu
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from whisperflow.languages import LANGUAGE_NAMES, configured_languages  # noqa: E402

CODES = list(LANGUAGE_NAMES)


def parse_languages(raw: str) -> list[str]:
    """Accept menu numbers and/or codes: "1,2", "en,zh", "1 ms"."""
    codes = []
    for token in raw.replace(",", " ").split():
        token = token.strip().lower()
        if token.isdigit() and 1 <= int(token) <= len(CODES):
            code = CODES[int(token) - 1]
        elif token in LANGUAGE_NAMES:
            code = token
        else:
            raise ValueError(f"'{token}' isn't a menu number or language code")
        if code not in codes:
            codes.append(code)
    if not codes:
        raise ValueError("pick at least one language")
    return codes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--current", action="store_true",
                    help="print the enabled language codes, comma-separated")
    ap.add_argument("--languages")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"])
    args = ap.parse_args()

    if args.list:
        for i, code in enumerate(CODES, 1):
            print(f"  {i:>2}. {LANGUAGE_NAMES[code]} ({code})")
        return 0

    config_path = ROOT / "config.json"
    source = config_path if config_path.exists() else ROOT / "config.example.json"
    config = json.loads(source.read_text(encoding="utf-8-sig"))

    if args.current:
        print(",".join(configured_languages(config)))
        return 0

    if args.languages is not None:
        try:
            codes = parse_languages(args.languages)
        except ValueError as exc:
            # stdout, not stderr: PowerShell 5.1 can turn native stderr
            # into a terminating error under $ErrorActionPreference=Stop.
            print(f"  {exc}")
            return 2
        config["languages"] = codes
        # One language: pin it. Several: auto-detect between them.
        config["language"] = codes[0] if len(codes) == 1 else None
        # ".en" models only understand English; switch to the multilingual
        # model of the same size when anything else is enabled.
        model = config.get("model_size", "base.en")
        if codes != ["en"] and model.endswith(".en"):
            config["model_size"] = model[:-3]
        print("  Languages: " + ", ".join(LANGUAGE_NAMES[c] for c in codes))

    if args.device:
        config["device"] = args.device
        config["compute_type"] = None  # right default per device
        print(f"  Device: {args.device}")

    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
