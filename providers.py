"""Runtime provider detection — Ollama, LM Studio, llama.cpp, Docker Model Runner.

Two-phase detection:
  1. Install check (filesystem / PATH) — is the binary/app present?
  2. Runtime probe (HTTP) — is the service actually answering?

Combined result is a three-state ``ProviderState``: NOT_INSTALLED / INSTALLED_OFF /
READY. UI uses this to give the user a meaningful action:
  - NOT_INSTALLED → offer install
  - INSTALLED_OFF → offer "start now" (automatic where possible)
  - READY         → ready to use
"""

import json
import logging
import os
import shutil
import ssl
import sys
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 0.8  # Match llmfit's 800ms timeout


class ProviderState(Enum):
    """Three-state lifecycle for a local inference provider."""

    NOT_INSTALLED = "not_installed"   # No binary / app on disk
    INSTALLED_OFF = "installed_off"   # Installed but service/server not answering
    READY = "ready"                   # HTTP probe succeeded


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def _http_get_json(url: str, timeout: float = TIMEOUT_SECONDS) -> dict | list | None:
    """Perform an HTTP GET and parse JSON response. Returns None on failure."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("HTTP GET %s failed: %s", url, exc)
        return None


@dataclass
class ProviderStatus:
    """Status of a single runtime provider.

    ``available`` is kept as a legacy boolean alias for ``state == READY``.
    New code should read ``state`` for the full three-way distinction.
    """

    name: str
    available: bool = False
    state: ProviderState = ProviderState.NOT_INSTALLED
    installed_models: set[str] = field(default_factory=set)
    install_hint: str = ""      # URL to installer page or CLI command
    start_action: str = ""      # UI action key: "start_ollama" / "start_lmstudio" / ""
    stop_action: str = ""       # UI action key: "stop_ollama" / "stop_lmstudio" / "" — only set when READY

    def __post_init__(self) -> None:
        # Keep ``available`` and ``state`` in sync so legacy callers setting
        # ``available=True`` get state=READY and vice-versa.
        if self.available and self.state == ProviderState.NOT_INSTALLED:
            self.state = ProviderState.READY
        elif self.state == ProviderState.READY:
            self.available = True

    @property
    def model_count(self) -> int:
        return len(self.installed_models)


# ---------------------------------------------------------------------------
# Install detection — filesystem / PATH based (service state independent)
# ---------------------------------------------------------------------------


def _ollama_is_installed() -> bool:
    """Is the Ollama binary on disk?  Daemon may or may not be running."""
    if shutil.which("ollama"):
        return True
    if sys.platform == "win32":
        for base_env in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(base_env)
            if not base:
                continue
            for rel in (("Ollama", "ollama.exe"),
                        ("Programs", "Ollama", "ollama.exe")):
                if (Path(base).joinpath(*rel)).exists():
                    return True
    elif sys.platform == "darwin":
        if Path("/Applications/Ollama.app").exists():
            return True
    return False


def _lmstudio_is_installed() -> bool:
    """Is the LM Studio app or CLI on disk?"""
    if shutil.which("lms"):
        return True
    if sys.platform == "win32":
        for base_env in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(base_env)
            if not base:
                continue
            for rel in (("LM Studio", "LM Studio.exe"),
                        ("Programs", "LM Studio", "LM Studio.exe")):
                if (Path(base).joinpath(*rel)).exists():
                    return True
    elif sys.platform == "darwin":
        if Path("/Applications/LM Studio.app").exists():
            return True
    # Linux AppImage lands anywhere — config directory is our best signal
    if (Path.home() / ".lmstudio").exists():
        return True
    return False


def _docker_is_installed() -> bool:
    return shutil.which("docker") is not None


def _ollama_installer_url() -> str:
    if sys.platform == "win32":
        return "https://ollama.com/download/windows"
    if sys.platform == "darwin":
        return "https://ollama.com/download/mac"
    return "https://ollama.com/download/linux"


def _lmstudio_installer_url() -> str:
    return "https://lmstudio.ai/"


def _docker_installer_url() -> str:
    return "https://www.docker.com/products/docker-desktop/"


# ---------------------------------------------------------------------------
# Per-provider detection (two-phase)
# ---------------------------------------------------------------------------


def _ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def detect_ollama() -> ProviderStatus:
    """Check if Ollama is running and list installed models."""
    status = ProviderStatus(name="Ollama")

    # Phase 2: runtime probe (happy path — skip install check if running)
    data = _http_get_json(f"{_ollama_host()}/api/tags")
    if data is not None:
        status.state = ProviderState.READY
        status.available = True
        status.stop_action = "stop_ollama"
        models = data.get("models", []) if isinstance(data, dict) else []
        for m in models:
            name = m.get("name", "") if isinstance(m, dict) else ""
            if name:
                status.installed_models.add(name)
        return status

    # Phase 1: not running — is it at least installed?
    if _ollama_is_installed():
        status.state = ProviderState.INSTALLED_OFF
        status.start_action = "start_ollama"
    else:
        status.state = ProviderState.NOT_INSTALLED
        status.install_hint = _ollama_installer_url()
    return status


def _lmstudio_models_dir() -> Path:
    """LM Studio's models directory — honours a user-customised location.

    Reads ``downloadsFolder`` from ~/.lmstudio/settings.json (set when the user
    moves their models folder) and falls back to the cross-platform default.
    """
    default = Path.home() / ".lmstudio" / "models"
    settings = Path.home() / ".lmstudio" / "settings.json"
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
        folder = data.get("downloadsFolder")
        if isinstance(folder, str) and folder.strip():
            custom = Path(folder)
            if custom.is_dir():
                return custom
    except (OSError, ValueError):
        pass
    return default


def _scan_lmstudio_disk_models() -> set[str]:
    """Model names downloaded to LM Studio's models dir, independent of the server.

    Lets already-downloaded models still show as installed when LM Studio's
    local server isn't running (otherwise they look like they vanished).
    """
    names: set[str] = set()
    base = _lmstudio_models_dir()
    try:
        if base.is_dir():
            for gguf in base.rglob("*.gguf"):
                names.add(gguf.stem)          # file name (e.g. Model-Q4_K_M)
                names.add(gguf.parent.name)   # repo folder
                try:
                    rel = gguf.parent.relative_to(base)
                    names.add(str(rel).replace("\\", "/"))  # publisher/repo id
                except ValueError:
                    pass
    except OSError as exc:
        logger.debug("LM Studio disk scan failed: %s", exc)
    return names


def detect_lm_studio() -> ProviderStatus:
    """Check if LM Studio's server mode is running and list loaded models."""
    status = ProviderStatus(name="LM Studio")

    data = _http_get_json("http://localhost:1234/v1/models")
    if data is not None:
        status.state = ProviderState.READY
        status.available = True
        status.stop_action = "stop_lmstudio"
        models = data.get("data", []) if isinstance(data, dict) else []
        for m in models:
            model_id = m.get("id", "") if isinstance(m, dict) else ""
            if model_id:
                status.installed_models.add(model_id)
        # Union with on-disk models so nothing is missed.
        status.installed_models |= _scan_lmstudio_disk_models()
        return status

    if _lmstudio_is_installed():
        status.state = ProviderState.INSTALLED_OFF
        status.start_action = "start_lmstudio"
        # Server is off, but downloaded models are still on disk — surface them
        # so they don't appear to have disappeared after a restart/update.
        status.installed_models |= _scan_lmstudio_disk_models()
    else:
        status.state = ProviderState.NOT_INSTALLED
        status.install_hint = _lmstudio_installer_url()
    return status


def detect_llamacpp() -> ProviderStatus:
    """Check if llama.cpp (llama-server) is available on PATH."""
    status = ProviderStatus(name="llama.cpp")

    for binary in ("llama-server", "llama-cli", "llama.cpp"):
        if shutil.which(binary):
            status.state = ProviderState.READY
            status.available = True
            return status

    status.state = ProviderState.NOT_INSTALLED
    status.install_hint = "https://github.com/ggerganov/llama.cpp/releases"
    return status


def detect_docker_model_runner() -> ProviderStatus:
    """Check if Docker Model Runner is available."""
    status = ProviderStatus(name="Docker Model Runner")

    data = _http_get_json("http://localhost:12434/engines/v1/models", timeout=1.0)
    if data is not None:
        status.state = ProviderState.READY
        status.available = True
        status.stop_action = "stop_dmr"
        models = data.get("data", []) if isinstance(data, dict) else []
        for m in models:
            model_id = m.get("id", "") if isinstance(m, dict) else ""
            if model_id:
                status.installed_models.add(model_id)
        return status

    if _docker_is_installed():
        status.state = ProviderState.INSTALLED_OFF
        status.start_action = "start_dmr"
    else:
        status.state = ProviderState.NOT_INSTALLED
        status.install_hint = _docker_installer_url()
    return status


def detect_all_providers() -> list[ProviderStatus]:
    """Detect all supported runtime providers. Safe to call from any thread."""
    return [
        detect_ollama(),
        detect_lm_studio(),
        detect_llamacpp(),
        detect_docker_model_runner(),
    ]
