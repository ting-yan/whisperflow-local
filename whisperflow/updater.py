"""Update check: compare the running version against the latest GitHub release.

Uses only the standard library so the frozen exe stays lean. The repo is
public, so this works unauthenticated; callers still treat any failure
(offline, rate-limited, etc.) as "no update information", never as an
error the user sees.
"""

import json
import os
import urllib.request

REPO = "ting-yan/whisperflow-local"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def _parse(version: str):
    return tuple(int(p) for p in version.strip().lstrip("v").split("."))


def check_for_update(current_version: str):
    """Return (latest_version, download_url) if newer than current, else None.

    Raises on network/API failure — callers should swallow exceptions.
    A GITHUB_TOKEN env var is used if present (not required for this repo
    since it's public, but lets a private fork reuse this unchanged).
    """
    request = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "WhisperFlowLocal",
        },
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.load(response)

    latest = data["tag_name"].lstrip("v")
    if _parse(latest) > _parse(current_version):
        return latest, data["html_url"]
    return None
