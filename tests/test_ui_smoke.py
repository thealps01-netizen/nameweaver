"""Headless smoke tests for the PyQt layer.

Why these exist: every other suite tests the pure-python core and never imports
PyQt6, so app.py (the largest file in the project), workers.py, updater.py,
dialogs.py and widgets/* had no coverage at all. A renamed Qt API or a broken
signal connection there could only be discovered by launching the app.

These tests run on Qt's "offscreen" platform (set in conftest.py), so they work
on a CI runner with no desktop session. They assert wiring and data flow, not
visual output: a widget is built, real SystemSpecs/ModelFit data is pushed
through its public entry points, and the result is read back.
"""

from __future__ import annotations

import hashlib

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

import app as app_module
import dialogs as dialogs_module
import updater as updater_module
import workers as workers_module
from cfg import AppConfig
from models import load_all_models
from providers import ProviderState, ProviderStatus
from scoring import ModelFit
from widgets.chat_dialog import ChatDialog
from widgets.comparison import ComparisonDialog
from widgets.detail_panel import DetailPanel
from widgets.download_dialog import DownloadDialog, GgufPickerDialog
from widgets.engine_status import EngineStatusPill
from widgets.filter_bar import FilterBar
from widgets.hw_sim import HardwareSimPanel
from widgets.model_table import ModelTableModel
from widgets.status_bar import AppStatusBar
from widgets.system_bar import SystemBar

SCORE_COLUMN = 3  # ModelTableModel column holding the match score


def _fit(model, specs, context_limit: int = 4096) -> ModelFit:
    return ModelFit.analyze(model, specs, context_limit=context_limit)


def _statuses() -> list[ProviderStatus]:
    return [
        ProviderStatus(
            "Ollama",
            state=ProviderState.READY,
            installed_models={"llama3.1:8b"},
            start_action="start_ollama",
            stop_action="stop_ollama",
        ),
        ProviderStatus("LM Studio", state=ProviderState.INSTALLED_OFF),
        ProviderStatus("llama.cpp", state=ProviderState.NOT_INSTALLED, install_hint="https://x"),
    ]


# ── Detail panel ──────────────────────────────────────────────────────────────


def test_detail_panel_renders_and_clears_a_fit(qtbot, sample_specs, small_model):
    fit = _fit(small_model, sample_specs)
    panel = DetailPanel()
    qtbot.addWidget(panel)
    panel.set_theme("dark")

    panel.show_model(fit)
    assert f"{fit.score:.1f}" in panel._score_label.text()
    # Runnable format, but the model is not installed anywhere yet: Download is
    # offered, Run is not (widgets/detail_panel.py:259-273).
    assert panel._download_btn.isEnabled() is True
    assert panel._run_btn.isEnabled() is False
    assert panel._run_btn.toolTip() == "Install the model first via Download"

    fit.installed = True
    panel.show_model(fit)
    assert panel._run_btn.isEnabled() is True

    panel.show_model(None)
    assert panel._score_label.text() == ""
    assert panel._run_btn.isEnabled() is False


def test_detail_panel_disables_download_for_engine_incompatible_formats(
    qtbot, sample_specs, small_model
):
    """AWQ/GPTQ cannot be loaded by the local engines, so neither action applies."""
    small_model.format = "awq"
    panel = DetailPanel()
    qtbot.addWidget(panel)

    panel.show_model(_fit(small_model, sample_specs))

    assert panel._download_btn.isEnabled() is False
    assert panel._run_btn.isEnabled() is False
    assert "GGUF" in panel._download_btn.toolTip()


# ── Model table ───────────────────────────────────────────────────────────────


def test_model_table_model_publishes_fits(qtbot, sample_specs, small_model, large_model):
    model = ModelTableModel()
    model.set_theme("gruvbox")
    model.set_data([_fit(small_model, sample_specs), _fit(large_model, sample_specs)])

    assert model.rowCount() == 2
    assert model.columnCount() > SCORE_COLUMN
    assert model.checked_fits() == []
    assert model.data(model.index(0, SCORE_COLUMN), Qt.ItemDataRole.DisplayRole) is not None
    assert model.get_fit(0) is not None


# ── Filter bar ────────────────────────────────────────────────────────────────


def test_filter_bar_round_trips_its_state(qtbot):
    bar = FilterBar()
    qtbot.addWidget(bar)
    bar.populate_providers(["Ollama", "LM Studio"])
    bar.populate_quants(["Q4_K_M", "Q8_0"])
    bar.populate_licenses(["mit", "apache-2.0"])

    bar.set_score_preference(0.8)
    assert bar.score_preference == pytest.approx(0.8)
    assert isinstance(bar.get_filters(), dict)

    bar.reset_filters()
    assert bar.search_text == ""
    assert bar.provider_filter == ""
    assert bar.installed_only is False


# ── System bar / status bar / engine pill ─────────────────────────────────────


def test_system_bar_renders_hardware_and_providers(qtbot, sample_specs):
    bar = SystemBar()
    qtbot.addWidget(bar)
    bar.update_hardware(sample_specs)
    bar.update_providers(_statuses(), theme_name="dark")
    bar.refresh_theme("light")


def test_status_bar_and_engine_pill_accept_status(qtbot):
    status = AppStatusBar()
    qtbot.addWidget(status)
    status.set_theme_name("dark")
    status.set_version("0.1.29")
    status.set_model_count(1038, 12)
    status.set_hw_sim(True)

    pill = EngineStatusPill("dark")
    qtbot.addWidget(pill)
    pill.update_status(_statuses())
    pill.set_provider_busy("Ollama", True, "start")
    pill.set_provider_busy("Ollama", False, "start")
    pill.refresh_theme("nord")


def test_hw_sim_panel_takes_real_specs(qtbot, sample_specs):
    panel = HardwareSimPanel()
    qtbot.addWidget(panel)
    panel.set_real_specs(sample_specs)
    assert panel.is_active is False
    panel.set_theme("solarized")


# ── Dialogs ───────────────────────────────────────────────────────────────────


def test_comparison_dialog_shows_both_models(qtbot, sample_specs, small_model, large_model):
    fits = [_fit(small_model, sample_specs), _fit(large_model, sample_specs)]
    dialog = ComparisonDialog(fits, theme_name="dark")
    qtbot.addWidget(dialog)

    labels = " ".join(lbl.text() for lbl in dialog.findChildren(QLabel))
    assert small_model.name in labels
    assert large_model.name in labels


def test_chat_dialog_lists_providers_and_starts_empty(qtbot):
    dialog = ChatDialog(
        "llama3.1:8b",
        ["Ollama", "LM Studio"],
        model_ids={"Ollama": "llama3.1:8b"},
        supports_vision=False,
        theme_name="nord",
    )
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Chat — llama3.1:8b"
    assert dialog._provider_combo.count() == 2
    assert dialog._input.placeholderText() != ""


def test_about_and_alert_dialogs_build(qtbot):
    about = dialogs_module.AboutDialog(theme_name="dark")
    qtbot.addWidget(about)
    alert = dialogs_module.AlertDialog("Something happened", "Details here", theme_name="dark")
    qtbot.addWidget(alert)
    assert "Details here" in " ".join(lbl.text() for lbl in alert.findChildren(QLabel))


def test_gguf_picker_marks_the_recommended_quant(qtbot):
    files = [
        {"path": "m.Q4_K_M.gguf", "size": 4_000_000_000},
        {"path": "m.Q8_0.gguf", "size": 8_000_000_000},
    ]
    dialog = GgufPickerDialog("org/repo", files, recommended_quant="Q4_K_M")
    qtbot.addWidget(dialog)

    assert dialog.selected_filename == ""  # nothing chosen until the user picks
    assert dialog._table.rowCount() == len(files)
    descriptions = [dialog._table.item(row, 3).text() for row in range(len(files))]
    assert any("Recommended" in text for text in descriptions)


def test_download_dialog_starts_clean(qtbot):
    worker = workers_module.DownloadWorker(
        workers_module.DownloadWorker.KIND_OLLAMA, model_name="gemma2:2b"
    )
    dialog = DownloadDialog(worker, "Downloading gemma2:2b")
    qtbot.addWidget(dialog)
    assert dialog.success is False


# ── Updater integrity gate (no network: the downloads are file:// URLs) ───────


def _installer(tmp_path, payload: bytes):
    path = tmp_path / "Nameweaver_Setup.exe"
    path.write_bytes(payload)
    return path


def test_installer_downloader_refuses_a_bad_checksum(qtbot, tmp_path):
    installer = _installer(tmp_path, b"pretend installer")
    sidecar = tmp_path / "Nameweaver_Setup.exe.sha256"
    sidecar.write_text(
        hashlib.sha256(b"a different file").hexdigest() + "  Nameweaver_Setup.exe\n"
    )

    downloader = updater_module.InstallerDownloader(installer.as_uri())
    errors, finished = [], []
    downloader.error.connect(errors.append)
    downloader.finished.connect(finished.append)

    downloader._run()  # the whole verify-and-run pipeline, without the QThread

    assert errors and "checksum" in errors[0].lower()
    assert finished == [], "an installer with a mismatched hash must never be run"


def test_installer_downloader_refuses_without_a_sidecar(qtbot, tmp_path):
    installer = _installer(tmp_path, b"pretend installer")

    downloader = updater_module.InstallerDownloader(installer.as_uri())
    errors, finished = [], []
    downloader.error.connect(errors.append)
    downloader.finished.connect(finished.append)

    downloader._run()

    assert errors and "verif" in errors[0].lower()
    assert finished == [], "an unverifiable installer must never be run"


def test_installer_downloader_accepts_a_matching_checksum(qtbot, tmp_path):
    payload = b"pretend installer"
    installer = _installer(tmp_path, payload)
    sidecar = tmp_path / "Nameweaver_Setup.exe.sha256"
    sidecar.write_text(hashlib.sha256(payload).hexdigest() + "  Nameweaver_Setup.exe\n")

    downloader = updater_module.InstallerDownloader(installer.as_uri())
    errors, finished = [], []
    downloader.error.connect(errors.append)
    downloader.finished.connect(finished.append)

    downloader._run()

    assert errors == []
    assert len(finished) == 1
    assert finished[0].endswith("Nameweaver_Setup.exe")


# ── Brace escapes inside f-strings ────────────────────────────────────────────


def test_no_f_string_keeps_an_unexpanded_brace_escape():
    """A `{{` or `}}` left inside an f-string segment reaches QSS/regex verbatim.

    Splitting a long f-string to stay under the line limit is the usual way this
    happens (ruff E501): the continuation is a *plain* string, so it is not
    processed as an f-string and an escaped brace written there stays doubled.
    Verified on Python 3.11 and 3.14: `f"a{{" "b}}"` evaluates to `a{b}}` — the
    f-string half unescapes its braces, the plain half keeps both.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for part in node.values:
                    if (
                        isinstance(part, ast.Constant)
                        and isinstance(part.value, str)
                        and ("{{" in part.value or "}}" in part.value)
                    ):
                        offenders.append(f"{path.name}:{node.lineno} {part.value!r}")

    assert offenders == [], "unexpanded brace escape(s): " + "; ".join(offenders)


# ── Main window: the primary flow ─────────────────────────────────────────────


class _StubSignal:
    def connect(self, *_args, **_kwargs):
        pass


class _StubUpdateChecker:
    """Replaces the GitHub release check so no test touches the network."""

    update_available = _StubSignal()
    no_update = _StubSignal()
    check_failed = _StubSignal()

    def __init__(self, owner: str, repo: str, parent=None):
        self.started = False

    def start(self) -> None:
        self.started = True


def test_main_window_boots_and_scores_the_catalog(qtbot, monkeypatch, sample_specs):
    """Boot the real MainWindow, then drive specs -> fits -> table."""
    monkeypatch.setattr(app_module, "UpdateChecker", _StubUpdateChecker)
    monkeypatch.setattr(app_module, "load_config", lambda: AppConfig(theme="dark"))
    monkeypatch.setattr(app_module, "save_config", lambda _cfg: None)
    monkeypatch.setattr(app_module.MainWindow, "_start_detection", lambda self: None)
    monkeypatch.setattr(app_module.MainWindow, "_apply_dwm_dark_title_bar", lambda self: None)

    window = app_module.MainWindow()
    qtbot.addWidget(window)

    assert window._update_checker.started is True, "startup update check not wired"
    assert window._table_model.rowCount() == 0

    # Detection normally fills the catalog; do it directly so the test does not
    # probe the host's real hardware or local engines.
    window._models = load_all_models()
    assert window._models, "embedded catalog data/models.json did not load"

    window._on_hardware_detected(sample_specs)
    qtbot.waitUntil(
        lambda: window._table_model.rowCount() == len(window._models), timeout=30_000
    )

    assert len(window._fits) == len(window._models)
    assert window._specs is sample_specs
    assert window._table_view.horizontalHeader().sortIndicatorSection() == SCORE_COLUMN
    assert window._status_bar is not None
