"""QThread-based background workers for async operations."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from hw import SystemSpecs
from models import LlmModel, load_all_models
from providers import ProviderStatus, detect_all_providers
from scoring import ModelFit, analyze_all

logger = logging.getLogger(__name__)


class HardwareWorker(QThread):
    """Detect system hardware in background."""

    finished = pyqtSignal(object)  # SystemSpecs
    error = pyqtSignal(str)

    def run(self) -> None:
        try:
            specs = SystemSpecs.detect()
            self.finished.emit(specs)
        except Exception as exc:
            logger.error("Hardware detection failed: %s", exc)
            self.error.emit(str(exc))


class ProviderWorker(QThread):
    """Detect runtime providers in background."""

    finished = pyqtSignal(list)  # list[ProviderStatus]
    error = pyqtSignal(str)

    def run(self) -> None:
        try:
            providers = detect_all_providers()
            self.finished.emit(providers)
        except Exception as exc:
            logger.error("Provider detection failed: %s", exc)
            self.error.emit(str(exc))


class ProviderPoller(QThread):
    """Periodically re-detect providers so the UI reflects live state.

    Emits ``status_changed`` only when the aggregate state actually changes —
    avoids spurious UI repaints. Caller is responsible for stopping the
    thread on app shutdown via ``requestInterruption()``.
    """

    status_changed = pyqtSignal(list)  # list[ProviderStatus]

    def __init__(self, interval_seconds: int = 10, parent=None):
        super().__init__(parent)
        self._interval_ms = int(interval_seconds * 1000)
        self._last_signature: tuple | None = None

    def run(self) -> None:
        while not self.isInterruptionRequested():
            try:
                providers = detect_all_providers()
                sig = tuple(
                    (p.name, p.state.value, len(p.installed_models))
                    for p in providers
                )
                if sig != self._last_signature:
                    self._last_signature = sig
                    self.status_changed.emit(providers)
            except Exception as exc:
                logger.debug("Provider poll failed: %s", exc)

            # Sleep in short chunks so interruption is responsive
            slept = 0
            while slept < self._interval_ms and not self.isInterruptionRequested():
                self.msleep(250)
                slept += 250


class ProviderStartWorker(QThread):
    """Launch a provider service in the background.

    Wraps ``provider_control.start_provider(action_key)`` so the UI thread
    doesn't block on ``_wait_for_http_ready`` (up to 10 seconds).
    """

    finished = pyqtSignal(bool)  # success
    error = pyqtSignal(str)

    def __init__(self, action_key: str, parent=None):
        super().__init__(parent)
        self._action_key = action_key

    def run(self) -> None:
        try:
            from provider_control import start_provider
            ok = start_provider(self._action_key)
            self.finished.emit(ok)
        except Exception as exc:
            logger.error("Provider start failed: %s", exc)
            self.error.emit(str(exc))


class ProviderStopWorker(QThread):
    """Stop a provider service in the background."""

    finished = pyqtSignal(bool)  # success
    error = pyqtSignal(str)

    def __init__(self, action_key: str, parent=None):
        super().__init__(parent)
        self._action_key = action_key

    def run(self) -> None:
        try:
            from provider_control import stop_provider
            ok = stop_provider(self._action_key)
            self.finished.emit(ok)
        except Exception as exc:
            logger.error("Provider stop failed: %s", exc)
            self.error.emit(str(exc))


class ScoringWorker(QThread):
    """Score all models against hardware in background."""

    finished = pyqtSignal(list)  # list[ModelFit]
    progress = pyqtSignal(int)  # percent
    error = pyqtSignal(str)

    def __init__(
        self,
        models: list[LlmModel],
        specs: SystemSpecs,
        context_limit: int | None = None,
        preference: float = 0.5,
        parent=None,
    ):
        super().__init__(parent)
        self._models = models
        self._specs = specs
        self._context_limit = context_limit
        self._preference = preference

    def run(self) -> None:
        try:
            fits = []
            total = len(self._models)
            for i, model in enumerate(self._models):
                try:
                    fit = ModelFit.analyze(
                        model,
                        self._specs,
                        self._context_limit,
                        preference=self._preference,
                    )
                    fits.append(fit)
                except Exception as exc:
                    logger.debug("Failed to score %s: %s", model.name, exc)

                if total > 0 and (i + 1) % max(1, total // 20) == 0:
                    self.progress.emit(int((i + 1) / total * 100))

            from scoring import rank_models

            fits = rank_models(fits)
            self.finished.emit(fits)
        except Exception as exc:
            logger.error("Scoring failed: %s", exc)
            self.error.emit(str(exc))


class ModelLoadWorker(QThread):
    """Load model database in background (embedded + HF cache merged)."""

    finished = pyqtSignal(list)  # list[LlmModel]
    error = pyqtSignal(str)

    def run(self) -> None:
        try:
            models = load_all_models()
            self.finished.emit(models)
        except Exception as exc:
            logger.error("Model loading failed: %s", exc)
            self.error.emit(str(exc))


class InferenceWorker(QThread):
    """Stream tokens from a local provider in the background."""

    token_received = pyqtSignal(str)
    finished_response = pyqtSignal(str)  # Full concatenated response
    error = pyqtSignal(str)

    def __init__(
        self,
        model_name: str,
        provider: str,
        prompt: str,
        system: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._model_name = model_name
        self._provider = provider
        self._prompt = prompt
        self._system = system
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _should_cancel(self) -> bool:
        return self._cancel

    def run(self) -> None:
        try:
            from runner import run_model

            buffer: list[str] = []
            for token in run_model(
                self._model_name,
                self._provider,
                self._prompt,
                system=self._system,
                should_cancel=self._should_cancel,
            ):
                if self._cancel:
                    break
                buffer.append(token)
                self.token_received.emit(token)

            self.finished_response.emit("".join(buffer))
        except Exception as exc:
            logger.error("Inference worker failed: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class DownloadWorker(QThread):
    """Run an Ollama pull or HF GGUF download in the background."""

    progress = pyqtSignal(int, str)  # percent (or -1 if unknown), status
    finished = pyqtSignal(bool, str)  # success, message/path
    error = pyqtSignal(str)

    # Source kinds
    KIND_OLLAMA = "ollama"
    KIND_GGUF = "gguf"

    def __init__(
        self,
        kind: str,
        *,
        model_name: str = "",
        repo_id: str = "",
        filename: str = "",
        dest_dir=None,
        token: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._kind = kind
        self._model_name = model_name
        self._repo_id = repo_id
        self._filename = filename
        self._dest_dir = dest_dir
        self._token = token
        self._cancel = False
        # Track last status message so a failure surfaces the actual cause
        # (e.g. "Error: pull model manifest: file does not exist") instead
        # of being overwritten by a generic "pull failed".
        self._last_status = ""

    def cancel(self) -> None:
        self._cancel = True

    def _should_cancel(self) -> bool:
        return self._cancel

    def run(self) -> None:
        try:
            from downloader import download_gguf, pull_ollama

            def on_prog(pct: int, msg: str) -> None:
                if msg:
                    self._last_status = msg
                self.progress.emit(pct, msg)

            if self._kind == self.KIND_OLLAMA:
                ok = pull_ollama(
                    self._model_name,
                    on_progress=on_prog,
                    should_cancel=self._should_cancel,
                )
                if ok:
                    msg = self._model_name
                else:
                    # Prefer the last error we saw over a generic label
                    msg = self._last_status or "Ollama pull failed"
                    if not msg.lower().startswith("error"):
                        msg = f"Pull failed: {msg}"
                self.finished.emit(ok, msg)
            elif self._kind == self.KIND_GGUF:
                path = download_gguf(
                    self._repo_id,
                    self._filename,
                    self._dest_dir,
                    token=self._token,
                    on_progress=on_prog,
                    should_cancel=self._should_cancel,
                )
                if path is not None:
                    msg = str(path)
                else:
                    msg = self._last_status or "GGUF download failed"
                    if not msg.lower().startswith("error"):
                        msg = f"Download failed: {msg}"
                self.finished.emit(path is not None, msg)
            else:
                self.error.emit(f"Unknown download kind: {self._kind}")
        except Exception as exc:
            logger.error("Download worker failed: %s", exc, exc_info=True)
            self.error.emit(str(exc))


class HFUpdateWorker(QThread):
    """Fetch latest trending + popular models from HuggingFace in background.

    Emits the merged catalog (embedded + cache) after writing cache.
    """

    progress = pyqtSignal(int, str)  # percent, message
    finished = pyqtSignal(list)  # list[LlmModel] — full merged catalog
    error = pyqtSignal(str)

    def __init__(
        self,
        token: str = "",
        limit: int = 200,
        fetch_config: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._token = token
        self._limit = limit
        self._fetch_config = fetch_config

    def run(self) -> None:
        try:
            from hf_api import save_cache, update_catalog

            fetched = update_catalog(
                token=self._token,
                limit=self._limit,
                fetch_config=self._fetch_config,
                on_progress=lambda pct, msg: self.progress.emit(pct, msg),
            )
            if fetched:
                save_cache(fetched)

            merged = load_all_models()
            self.finished.emit(merged)
        except Exception as exc:
            logger.error("HF update failed: %s", exc, exc_info=True)
            self.error.emit(str(exc))
