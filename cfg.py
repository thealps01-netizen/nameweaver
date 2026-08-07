"""Configuration management with atomic writes, logging setup, and validation."""

import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "Nameweaver"


def config_dir() -> Path:
    """Return the application config directory, creating it if needed."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
        if not base:
            base = str(Path.home() / "AppData" / "Local")
        path = Path(base) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        if not xdg:
            xdg = str(Path.home() / ".config")
        path = Path(xdg) / APP_NAME.lower()
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    """Return the log directory, creating it if needed."""
    path = config_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppConfig:
    """Application configuration with defaults."""

    theme: str = "dark"
    window_width: int = 1200
    window_height: int = 800
    window_x: int = -1
    window_y: int = -1
    splitter_sizes: list[int] = field(default_factory=lambda: [700, 300])
    last_sort_column: str = "score"
    last_sort_order: str = "descending"
    filters: dict = field(default_factory=dict)
    hw_overrides: dict | None = None
    check_updates_on_start: bool = True
    hf_token: str = ""
    last_hf_update: str = ""  # ISO-8601 timestamp of last HF model update
    disabled_gpus: list[str] = field(default_factory=list)  # GPU names excluded from fit calc
    score_preference: float = 0.5  # 0.0 = pure speed, 0.5 = neutral, 1.0 = pure quality

    def validate(self) -> "AppConfig":
        """Validate and sanitize config values, clamping to safe ranges."""
        if self.theme not in ("dark", "light", "dracula", "nord", "gruvbox", "solarized"):
            self.theme = "dark"
        self.window_width = max(400, min(self.window_width, 4000))
        self.window_height = max(300, min(self.window_height, 3000))
        if not isinstance(self.splitter_sizes, list) or len(self.splitter_sizes) != 2:
            self.splitter_sizes = [700, 300]
        if self.last_sort_order not in ("ascending", "descending"):
            self.last_sort_order = "descending"
        if not isinstance(self.filters, dict):
            self.filters = {}
        # Clamp preference to [0, 1]
        try:
            self.score_preference = max(0.0, min(1.0, float(self.score_preference)))
        except (TypeError, ValueError):
            self.score_preference = 0.5
        return self


def _config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> AppConfig:
    """Load config from disk with corrupt-file recovery."""
    path = _config_path()
    if not path.exists():
        return AppConfig()

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Config root must be a JSON object")
        config = AppConfig(**{k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__})
        return config.validate()
    except Exception as exc:
        logger.warning("Corrupt config file, backing up: %s", exc)
        backup = path.with_suffix(f".corrupt_{int(time.time())}")
        try:
            path.rename(backup)
            logger.info("Backed up corrupt config to %s", backup)
        except OSError:
            pass
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """Atomically save config to disk."""
    path = _config_path()
    data = json.dumps(asdict(config), indent=2, ensure_ascii=False)

    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def setup_logging(level: int = logging.INFO) -> None:
    """Configure rotating file + stderr logging."""
    root = logging.getLogger()
    root.setLevel(level)

    # Rotating file handler
    log_file = log_dir() / "nameweaver.log"
    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root.addHandler(file_handler)

    # Stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(
        logging.Formatter("%(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(stderr_handler)

    logger.info("Logging initialized — log file: %s", log_file)
