"""Provider lifecycle actions — start/install without leaving the app.

Each ``start_*`` function tries to bring a provider from INSTALLED_OFF to
READY by launching its service in the background and polling the HTTP probe
until it answers. Returns True on success.

``install_*`` helpers wrap the OS package manager (winget / brew / apt) or
fall back to opening the installer URL in the browser.

All long-running operations should be wrapped in a QThread by the caller —
these functions block up to ~10 seconds waiting for readiness.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from providers import (
    _docker_is_installed,
    _http_get_json,
    _lmstudio_is_installed,
    _lmstudio_installer_url,
    _ollama_host,
    _ollama_installer_url,
    _ollama_is_installed,
)

logger = logging.getLogger(__name__)

# ── Windows: run console tools without flashing a cmd window ────────────────────
_subprocess_run = subprocess.run  # keep the real one for the wrapper below

if sys.platform == "win32":
    _CREATE_NO_WINDOW = 0x08000000
    _CREATE_NEW_PROCESS_GROUP = 0x00000200

    def _hidden_startupinfo():
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si
else:
    _CREATE_NO_WINDOW = 0
    _CREATE_NEW_PROCESS_GROUP = 0

    def _hidden_startupinfo():
        return None


def _run(cmd, **kwargs):
    """subprocess.run that never pops a console window on Windows."""
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", _CREATE_NO_WINDOW)
        kwargs.setdefault("startupinfo", _hidden_startupinfo())
    return _subprocess_run(cmd, **kwargs)


# How long to wait for a service to become ready after we launch it.
_READY_TIMEOUT_SECONDS = 10.0
_READY_POLL_INTERVAL = 0.5


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _wait_for_http_ready(url: str, timeout: float = _READY_TIMEOUT_SECONDS) -> bool:
    """Poll an HTTP endpoint until it responds or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _http_get_json(url, timeout=0.3) is not None:
            return True
        time.sleep(_READY_POLL_INTERVAL)
    return False


def _popen_detached(cmd: list[str]) -> subprocess.Popen | None:
    """Start a process detached from the parent so it keeps running."""
    try:
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            # CREATE_NO_WINDOW keeps the daemon AND its child runner processes
            # windowless. DETACHED_PROCESS is deliberately NOT combined here:
            # Windows ignores CREATE_NO_WINDOW when DETACHED_PROCESS is set,
            # which let `ollama serve`'s runners spawn their own cmd windows.
            kwargs["creationflags"] = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
            kwargs["startupinfo"] = _hidden_startupinfo()
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(cmd, **kwargs)
    except (OSError, FileNotFoundError) as exc:
        logger.warning("Failed to launch %s: %s", cmd, exc)
        return None


def _find_ollama_binary() -> str | None:
    """Locate the ollama executable on disk (PATH + common install dirs)."""
    path_hit = shutil.which("ollama")
    if path_hit:
        return path_hit
    if sys.platform == "win32":
        for base_env in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(base_env)
            if not base:
                continue
            for rel in (("Ollama", "ollama.exe"),
                        ("Programs", "Ollama", "ollama.exe")):
                exe = Path(base).joinpath(*rel)
                if exe.exists():
                    return str(exe)
    return None


# ---------------------------------------------------------------------------
# Start actions
# ---------------------------------------------------------------------------


def start_ollama_service() -> bool:
    """Start the Ollama daemon in the background and wait for readiness.

    Returns True if the service is responding to ``/api/tags`` when done.
    Safe to call when already running (short-circuit via initial probe).
    """
    probe_url = f"{_ollama_host()}/api/tags"

    # Already running?
    if _http_get_json(probe_url, timeout=0.3) is not None:
        return True

    if not _ollama_is_installed():
        logger.info("Ollama not installed — cannot start")
        return False

    try:
        if sys.platform == "darwin":
            # macOS: launch the app bundle — it registers the tray daemon
            subprocess.Popen(
                ["open", "-a", "Ollama"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "win32":
            # Windows: the installer registers a tray service; launching
            # the exe silently is enough to bring it up
            exe = _find_ollama_binary()
            if exe:
                _popen_detached([exe, "serve"])
            else:
                return False
        else:
            # Linux: user-level ``ollama serve``
            _popen_detached(["ollama", "serve"])
    except Exception as exc:
        logger.warning("start_ollama_service failed: %s", exc)
        return False

    return _wait_for_http_ready(probe_url)


def start_lmstudio_server() -> bool:
    """Start LM Studio's OpenAI-compat server via the ``lms`` CLI.

    Requires LM Studio 0.3+ where ``lms`` is on PATH. Older versions need
    the user to click "Start Server" in the GUI — caller handles that
    fallback with a guided modal.
    """
    probe_url = "http://localhost:1234/v1/models"

    if _http_get_json(probe_url, timeout=0.3) is not None:
        return True

    if not shutil.which("lms"):
        return False  # Signal caller to show the guided-modal fallback

    try:
        # Non-blocking — returns quickly once server is spawned
        _run(
            ["lms", "server", "start"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("lms server start failed: %s", exc)
        return False

    return _wait_for_http_ready(probe_url)


def open_lmstudio_app() -> bool:
    """Launch the LM Studio GUI — used when ``lms`` CLI is unavailable.

    The app itself has a "Start Server" button the user must click; the
    UI layer shows a guided modal explaining this.
    """
    if not _lmstudio_is_installed():
        return False

    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "LM Studio"],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        if sys.platform == "win32":
            for base_env in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
                base = os.environ.get(base_env)
                if not base:
                    continue
                for rel in (("LM Studio", "LM Studio.exe"),
                            ("Programs", "LM Studio", "LM Studio.exe")):
                    exe = Path(base).joinpath(*rel)
                    if exe.exists():
                        _popen_detached([str(exe)])
                        return True
        else:
            # Linux: hope it's on PATH
            _popen_detached(["lm-studio"])
            return True
    except Exception as exc:
        logger.warning("open_lmstudio_app failed: %s", exc)
    return False


def start_docker_model_runner() -> bool:
    """Best-effort DMR start — ensures Docker Desktop is running.

    Docker Desktop must be launched for the model-runner endpoint to come
    up. We simply try to start the Desktop app; the user may still need to
    enable Model Runner in settings manually.
    """
    if not _docker_is_installed():
        return False

    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Docker"],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            # Docker Desktop service — try common install dir
            candidates = [
                Path("C:/Program Files/Docker/Docker/Docker Desktop.exe"),
            ]
            for exe in candidates:
                if exe.exists():
                    _popen_detached([str(exe)])
                    break
        else:
            _popen_detached(["systemctl", "--user", "start", "docker-desktop"])
    except Exception as exc:
        logger.warning("start_docker_model_runner failed: %s", exc)
        return False

    return _wait_for_http_ready(
        "http://localhost:12434/engines/v1/models", timeout=20.0
    )


# Dispatch table — UI passes ``start_action`` string from ProviderStatus.
START_ACTIONS = {
    "start_ollama": start_ollama_service,
    "start_lmstudio": start_lmstudio_server,
    "start_dmr": start_docker_model_runner,
}


def start_provider(action_key: str) -> bool:
    """Run the action identified by ``ProviderStatus.start_action``."""
    fn = START_ACTIONS.get(action_key)
    if fn is None:
        logger.warning("Unknown start action: %r", action_key)
        return False
    return fn()


# ---------------------------------------------------------------------------
# Stop actions
# ---------------------------------------------------------------------------


def _wait_for_http_gone(url: str, timeout: float = 5.0) -> bool:
    """Poll until the HTTP endpoint stops responding, or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _http_get_json(url, timeout=0.3) is None:
            return True
        time.sleep(_READY_POLL_INTERVAL)
    return False


def stop_ollama_service() -> bool:
    """Kill the Ollama daemon. Returns True when the HTTP probe goes dark."""
    probe_url = f"{_ollama_host()}/api/tags"
    if _http_get_json(probe_url, timeout=0.3) is None:
        return True  # already down

    try:
        if sys.platform == "win32":
            _run(
                ["taskkill", "/F", "/IM", "ollama.exe"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            # Also kill the tray app if present
            _run(
                ["taskkill", "/F", "/IM", "ollama app.exe"],
                capture_output=True,
                timeout=10,
                check=False,
            )
        elif sys.platform == "darwin":
            _run(
                ["osascript", "-e", 'quit app "Ollama"'],
                capture_output=True,
                timeout=10,
                check=False,
            )
            _run(["pkill", "-x", "ollama"],
                           capture_output=True, timeout=5, check=False)
        else:
            _run(["pkill", "-x", "ollama"],
                           capture_output=True, timeout=5, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("stop_ollama_service failed: %s", exc)
        return False

    return _wait_for_http_gone(probe_url)


def stop_lmstudio_server() -> bool:
    """Stop LM Studio's OpenAI server via ``lms server stop``.

    Note: only stops the server — the GUI app stays open. If ``lms`` is not
    on PATH we can't do anything clean, so we return False and let the UI
    guide the user.
    """
    probe_url = "http://localhost:1234/v1/models"
    if _http_get_json(probe_url, timeout=0.3) is None:
        return True

    if not shutil.which("lms"):
        return False

    try:
        _run(
            ["lms", "server", "stop"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("lms server stop failed: %s", exc)
        return False

    return _wait_for_http_gone(probe_url)


def stop_docker_model_runner() -> bool:
    """We don't kill Docker Desktop — user may be using it for other things.

    Instead, open the Docker Desktop app so the user can stop Model Runner
    from its settings. Returns False so the UI shows a guidance message.
    """
    # No safe automatic way to toggle Model Runner off; bail.
    return False


STOP_ACTIONS = {
    "stop_ollama": stop_ollama_service,
    "stop_lmstudio": stop_lmstudio_server,
    "stop_dmr": stop_docker_model_runner,
}


def stop_provider(action_key: str) -> bool:
    """Run the action identified by ``ProviderStatus.stop_action``."""
    fn = STOP_ACTIONS.get(action_key)
    if fn is None:
        logger.warning("Unknown stop action: %r", action_key)
        return False
    return fn()


# ---------------------------------------------------------------------------
# Install actions (package managers)
# ---------------------------------------------------------------------------


def suggested_install_command(provider: str) -> str:
    """Return an OS-appropriate install command (or URL fallback).

    The UI shows this to the user and, with consent, runs it via
    ``run_install_command``.
    """
    p = provider.lower()
    if p == "ollama":
        if sys.platform == "win32":
            return "winget install --id Ollama.Ollama -e"
        if sys.platform == "darwin":
            return "brew install --cask ollama"
        return "curl -fsSL https://ollama.com/install.sh | sh"
    if p == "lm studio" or p == "lmstudio":
        if sys.platform == "win32":
            return "winget install --id ElementLabs.LMStudio -e"
        if sys.platform == "darwin":
            return "brew install --cask lm-studio"
        # Linux: AppImage — manual download
        return _lmstudio_installer_url()
    if p == "docker" or p == "docker model runner":
        if sys.platform == "win32":
            return "winget install --id Docker.DockerDesktop -e"
        if sys.platform == "darwin":
            return "brew install --cask docker"
        return "https://www.docker.com/products/docker-desktop/"
    return ""


def open_installer_page(provider: str) -> None:
    """Open the provider's installer URL in the default browser."""
    p = provider.lower()
    url = ""
    if p == "ollama":
        url = _ollama_installer_url()
    elif p == "lm studio" or p == "lmstudio":
        url = _lmstudio_installer_url()
    elif p == "docker" or p == "docker model runner":
        url = "https://www.docker.com/products/docker-desktop/"
    if url:
        webbrowser.open(url)


_KNOWN_PROVIDERS = ("ollama", "lm studio", "lmstudio", "docker", "docker model runner")


def _known_install_commands() -> set[str]:
    """All install commands we are willing to execute on this platform."""
    return {suggested_install_command(p) for p in _KNOWN_PROVIDERS} - {""}


def run_install_command(command: str) -> tuple[bool, str]:
    """Execute an install command; return (ok, combined_output).

    Only commands produced by ``suggested_install_command`` are executed —
    arbitrary strings are rejected to avoid shell injection. URLs open in
    the browser instead. Blocking — caller must run from a worker thread.
    """
    if not command:
        return False, "Empty command"

    # URLs are not commands — open the browser and bail
    if command.startswith("http://") or command.startswith("https://"):
        webbrowser.open(command)
        return True, f"Opened {command}"

    # Refuse anything we didn't generate ourselves. This blocks shell
    # injection via modified UI input while still allowing the one legit
    # curl|sh pipeline on Linux (Ollama installer).
    if command not in _known_install_commands():
        logger.warning("Rejected unknown install command: %r", command)
        return False, "Command not recognized"

    # Ollama's Linux installer requires a shell pipeline; everything else is
    # a plain argv we can split safely.
    needs_shell = "|" in command

    try:
        if needs_shell:
            result = _run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        else:
            result = _run(
                shlex.split(command, posix=(sys.platform != "win32")),
                shell=False,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"Command failed: {exc}"


# ---------------------------------------------------------------------------
# Removal / uninstall
# ---------------------------------------------------------------------------


def remove_model(provider_name: str, model_id: str) -> tuple[bool, str]:
    """Remove an installed model from the given engine. Returns (ok, message)."""
    p = (provider_name or "").strip().lower()
    if p == "ollama":
        return _remove_ollama(model_id)
    if p in ("lm studio", "lmstudio"):
        return _remove_lmstudio(model_id)
    return False, f"Removal isn't supported for {provider_name}."


def _remove_ollama(model_id: str) -> tuple[bool, str]:
    body = json.dumps({"name": model_id}).encode("utf-8")
    req = urllib.request.Request(
        f"{_ollama_host()}/api/delete",
        data=body,
        method="DELETE",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True, f"Removed {model_id} from Ollama."
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, f"{model_id} not found in Ollama."
        return False, f"Ollama error: {exc}"
    except (urllib.error.URLError, OSError) as exc:
        return False, f"Could not reach Ollama: {exc}"


def _remove_lmstudio(model_id: str) -> tuple[bool, str]:
    """Delete a model's folder from LM Studio's models directory (guarded)."""
    from models import name_matches_installed
    from providers import _lmstudio_models_dir

    base = _lmstudio_models_dir()
    if not base.is_dir():
        return False, "LM Studio models folder not found."
    base_resolved = base.resolve()

    target = None
    for gguf in base.rglob("*.gguf"):
        rel = gguf.parent.relative_to(base)
        candidates = [gguf.stem, gguf.parent.name, str(rel).replace("\\", "/")]
        if model_id in candidates or name_matches_installed(model_id, candidates):
            target = gguf.parent.resolve()
            break
    if target is None:
        return False, f"{model_id} not found on disk."

    # Safety: only ever delete a folder strictly inside the models directory.
    if target == base_resolved or base_resolved not in target.parents:
        return False, "Refusing to delete outside the LM Studio models folder."
    try:
        shutil.rmtree(target)
        return True, f"Deleted {target}."
    except OSError as exc:
        return False, f"Delete failed: {exc}"
