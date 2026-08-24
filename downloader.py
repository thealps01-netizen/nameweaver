"""Model download helpers — Ollama pull + HuggingFace GGUF download.

Both functions accept an ``on_progress(pct, msg)`` callback and return the
result path / True on success. They are designed to be wrapped in a QThread.
"""

from __future__ import annotations

import hashlib
import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

OLLAMA_PULL_URL = "http://localhost:11434/api/pull"
HF_RESOLVE_BASE = "https://huggingface.co"
USER_AGENT = "Nameweaver/0.2"

ProgressCallback = Callable[[int, str], None]


# ---------------------------------------------------------------------------
# Ollama pull
# ---------------------------------------------------------------------------


def pull_ollama(
    model_name: str,
    on_progress: ProgressCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> bool:
    """Pull an Ollama model via the REST API with streaming progress.

    Returns True on success. Emits progress via ``on_progress(pct, msg)``.
    """
    if not model_name:
        return False

    body = json.dumps({"name": model_name, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_PULL_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )

    def emit(pct: int, msg: str) -> None:
        if on_progress:
            on_progress(pct, msg)

    emit(0, f"Pulling {model_name}…")

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw in resp:
                if should_cancel and should_cancel():
                    emit(0, "Cancelled")
                    return False

                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                status = event.get("status", "")
                completed = event.get("completed")
                total = event.get("total")

                if isinstance(completed, int) and isinstance(total, int) and total > 0:
                    pct = int(completed / total * 100)
                    emit(pct, status)
                else:
                    emit(-1, status)

                if status == "success":
                    emit(100, "Pull complete")
                    return True

                if event.get("error"):
                    logger.error("Ollama pull error: %s", event["error"])
                    emit(0, f"Error: {event['error']}")
                    return False

        # Stream ended without explicit success
        emit(100, "Pull complete")
        return True

    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
        logger.error("Ollama pull failed (%s): %s", model_name, exc)
        emit(0, f"Connection error: {exc}")
        return False


# ---------------------------------------------------------------------------
# HuggingFace GGUF download
# ---------------------------------------------------------------------------


def _build_hf_request(url: str, token: str = "") -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def download_gguf(
    repo_id: str,
    filename: str,
    dest_dir: Path,
    token: str = "",
    on_progress: ProgressCallback | None = None,
    should_cancel: Callable[[], bool] | None = None,
    expected_sha256: str | None = None,
) -> Path | None:
    """Download a GGUF file from HuggingFace with a progress callback.

    Saves to ``dest_dir/filename``. Resumes are not supported (simple 1-shot).
    Returns the destination Path on success, None on failure.
    """
    if "/" not in repo_id or not filename:
        return None

    # HF tree API returns untrusted paths — reject anything that could escape
    # dest_dir (path separators, drive letters, parent refs, absolute paths).
    safe_name = Path(filename).name
    if (
        safe_name != filename
        or not safe_name
        or safe_name in (".", "..")
        or "\\" in filename
        or "/" in filename
    ):
        logger.error("Rejected unsafe GGUF filename: %r", filename)
        return None

    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = (dest_dir / safe_name).resolve()
    try:
        dest.relative_to(dest_dir)
    except ValueError:
        logger.error("Resolved path escapes dest_dir: %s", dest)
        return None
    tmp = dest.with_suffix(dest.suffix + ".part")

    url = f"{HF_RESOLVE_BASE}/{repo_id}/resolve/main/{urllib.parse.quote(filename)}"

    def emit(pct: int, msg: str) -> None:
        if on_progress:
            on_progress(pct, msg)

    emit(0, f"Connecting to {repo_id}…")

    ctx = ssl.create_default_context()
    sha = hashlib.sha256() if expected_sha256 else None

    try:
        req = _build_hf_request(url, token)
        with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
            total_bytes = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 512  # 512KB

            with open(tmp, "wb") as f:
                while True:
                    if should_cancel and should_cancel():
                        emit(0, "Cancelled")
                        try:
                            tmp.unlink()
                        except OSError:
                            pass
                        return None

                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    if sha:
                        sha.update(chunk)
                    downloaded += len(chunk)

                    if total_bytes > 0:
                        pct = int(downloaded / total_bytes * 100)
                        mb = downloaded / (1024 * 1024)
                        total_mb = total_bytes / (1024 * 1024)
                        emit(pct, f"{mb:.1f} / {total_mb:.1f} MB")
                    else:
                        mb = downloaded / (1024 * 1024)
                        emit(-1, f"{mb:.1f} MB downloaded")

        # Hash verification
        if sha and expected_sha256:
            digest = sha.hexdigest()
            if digest.lower() != expected_sha256.lower():
                logger.error(
                    "SHA256 mismatch for %s: expected %s, got %s",
                    filename, expected_sha256, digest,
                )
                emit(0, "SHA256 verification failed")
                try:
                    tmp.unlink()
                except OSError:
                    pass
                return None

        # Atomic rename
        tmp.replace(dest)
        emit(100, f"Saved to {dest}")
        return dest

    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
        logger.error("GGUF download failed (%s/%s): %s", repo_id, filename, exc)
        emit(0, f"Download error: {exc}")
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return None


def list_gguf_files(repo_id: str, token: str = "") -> list[dict]:
    """List GGUF files in an HF repo via the /api/models/{id}/tree endpoint."""
    if "/" not in repo_id:
        return []
    # URL-encode path components so display names with spaces (e.g.
    # "Mistral AI/Mistral-7B") don't crash urllib with a control-char error.
    # Real HF repo IDs rarely contain spaces, but model catalog provider
    # fields sometimes hold display names.
    org, _, name = repo_id.partition("/")
    safe_id = f"{urllib.parse.quote(org, safe='')}/{urllib.parse.quote(name, safe='')}"
    url = f"https://huggingface.co/api/models/{safe_id}/tree/main"
    req = _build_hf_request(url, token)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        logger.debug("Failed to list tree for %s: %s", repo_id, exc)
        return []

    if not isinstance(data, list):
        return []

    return [
        {
            "path": item.get("path", ""),
            "size": item.get("size", 0),
        }
        for item in data
        if isinstance(item, dict) and item.get("path", "").lower().endswith(".gguf")
    ]
