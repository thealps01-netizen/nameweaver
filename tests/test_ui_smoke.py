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
from models import LlmModel, load_all_models, ollama_tag_candidates
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
    # Download is the panel's only action now: running happens on My Models,
    # where the engine's own id is known, so no Run button exists here at all.
    assert panel._download_btn.isEnabled() is True
    assert not hasattr(panel, "_run_btn")
    assert not hasattr(panel, "run_requested")

    panel.show_model(None)
    assert panel._score_label.text() == ""


def test_detail_panel_disables_download_for_engine_incompatible_formats(
    qtbot, sample_specs, small_model
):
    """AWQ/GPTQ cannot be loaded by the local engines, so neither action applies."""
    small_model.format = "awq"
    panel = DetailPanel()
    qtbot.addWidget(panel)

    panel.show_model(_fit(small_model, sample_specs))

    assert panel._download_btn.isEnabled() is False
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
    # The catalog no longer claims to know what is installed: the filter and the
    # field it persisted are gone, and only the engines' own list (My Models)
    # says what is on disk.
    assert not hasattr(bar, "_installed_checkbox")
    assert "installed_only" not in bar.get_filters()


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
    sidecar.write_text(hashlib.sha256(b"a different file").hexdigest() + "  Nameweaver_Setup.exe\n")

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
    qtbot.waitUntil(lambda: window._table_model.rowCount() == len(window._models), timeout=30_000)

    assert len(window._fits) == len(window._models)
    assert window._specs is sample_specs
    assert window._table_view.horizontalHeader().sortIndicatorSection() == SCORE_COLUMN
    assert window._status_bar is not None


def test_detail_panel_says_an_embedding_model_cannot_chat(qtbot, sample_specs, small_model):
    """An embedder is not a chat model, and the panel says so where it matters."""
    small_model.use_case = "embedding"
    fit = _fit(small_model, sample_specs)
    panel = DetailPanel()
    qtbot.addWidget(panel)

    panel.show_model(fit)

    assert "No chat" in panel._details_label.text()
    # analyze() puts the reason where the panel shows notes.
    assert "embedding" in panel._notes_label.text().lower()


class TestMyModelsPageWiring:
    """The page is only useful if the window actually switches to it and feeds it."""

    def _window(self, qtbot, monkeypatch):
        monkeypatch.setattr(app_module, "UpdateChecker", _StubUpdateChecker)
        monkeypatch.setattr(app_module, "load_config", lambda: AppConfig(theme="dark"))
        monkeypatch.setattr(app_module, "save_config", lambda _cfg: None)
        monkeypatch.setattr(app_module.MainWindow, "_start_detection", lambda self: None)
        monkeypatch.setattr(app_module.MainWindow, "_apply_dwm_dark_title_bar", lambda self: None)
        window = app_module.MainWindow()
        qtbot.addWidget(window)
        return window

    def test_the_catalog_window_offers_no_place_to_run_a_model(self, qtbot, monkeypatch):
        """Run lives on My Models only — the catalog cannot start a chat."""
        window = self._window(qtbot, monkeypatch)
        assert window._pages.count() == 2
        assert window._pages.currentIndex() == 0

        assert not hasattr(window._detail_panel, "run_requested")
        assert not hasattr(window._table_view, "run_requested")
        assert not hasattr(window, "_on_run_requested")
        assert not hasattr(window, "_open_in_my_models")

    def test_switching_back_reveals_the_filters_again(self, qtbot, monkeypatch):
        window = self._window(qtbot, monkeypatch)

        window._show_page(1)
        window._show_page(0)

        assert window._pages.currentIndex() == 0
        assert window._nav_catalog_btn.isChecked() is True
        assert window._nav_my_models_btn.isChecked() is False

    def test_engine_rows_are_enriched_with_the_catalog(
        self, qtbot, monkeypatch, sample_specs, large_model
    ):
        from providers import InstalledModel, ProviderState, ProviderStatus

        window = self._window(qtbot, monkeypatch)

        # A row the engine reports, whose catalog name differs by qualifiers.
        large_model.name = "DeepSeek-R1-Distill-Qwen-7B"
        fit = _fit(large_model, sample_specs)
        fit.engine_ids = {"Ollama": "deepseek-r1:7b"}
        fit.likely_providers = ["Ollama"]
        window._fits = [fit]
        status = ProviderStatus(name="Ollama", state=ProviderState.READY, available=True)
        window._providers = [status]

        window._on_installed_models_listed(
            [
                InstalledModel(
                    engine="Ollama",
                    id="deepseek-r1:7b",
                    size_bytes=4 * 1024**3,
                    parameters="7B",
                    quantization="Q4_K_M",
                    capabilities=("completion", "tools"),
                    reported_by_engine=True,
                ),
                InstalledModel(
                    engine="Ollama",
                    id="some-embedder:latest",
                    capabilities=("embedding",),
                    reported_by_engine=True,
                ),
            ]
        )

        view = window._my_models
        assert view.row_count() == 2
        assert view.cell_text(0, 0) == "DeepSeek-R1-Distill-Qwen-7B"  # catalog name
        assert view.cell_text(0, 5) == "DeepSeek-R1-Distill-Qwen-7B"
        assert view.cell_text(0, 6) == "yes"
        assert view.run_button(0).isEnabled() is True
        # Engine says embedding-only → never runnable, and no catalog entry needed.
        assert view.cell_text(1, 6) == "no"
        assert view.run_button(1).isEnabled() is False


def test_engine_popup_rows_follow_their_engine_when_the_list_changes(qtbot):
    """Detection re-runs while the popup is open: each row must update from its
    own engine, not from whatever provider now sits at its position — and it must
    update at all (replacing the widget does not work, QWidgetAction keeps the
    first one it was given)."""
    from providers import ProviderState, ProviderStatus
    from widgets.engine_status import EngineStatusPill

    pill = EngineStatusPill("dark")
    qtbot.addWidget(pill)

    def _p(name, state, available):
        status = ProviderStatus(name=name, available=available)
        status.state = state
        return status

    pill.update_status(
        [
            _p("Ollama", ProviderState.READY, True),
            _p("LM Studio", ProviderState.INSTALLED_OFF, False),
        ]
    )
    pill._build_popup_menu()
    assert pill._popup_rows["LM Studio"]._state.text() == "— off"

    # Ollama disappears, llama.cpp appears, LM Studio starts up, order flips.
    pill.update_status(
        [
            _p("llama.cpp", ProviderState.NOT_INSTALLED, False),
            _p("LM Studio", ProviderState.READY, True),
        ]
    )
    pill._refresh_popup_rows()

    assert set(pill._popup_rows) == {"Ollama", "LM Studio"}  # a gone engine keeps its row
    assert pill._popup_rows["LM Studio"]._state.text() == "— running"
    assert pill._popup_rows["Ollama"]._name.text() == "Ollama"


def test_an_open_popup_shows_the_busy_state_of_its_engine(qtbot):
    from providers import ProviderState, ProviderStatus
    from widgets.engine_status import EngineStatusPill

    pill = EngineStatusPill("dark")
    qtbot.addWidget(pill)
    status = ProviderStatus(name="Ollama", available=False, start_action="start_ollama")
    status.state = ProviderState.INSTALLED_OFF
    pill.update_status([status])

    menu = pill._build_popup_menu()
    pill._current_menu = menu
    menu.setVisible(True)
    pill.set_provider_busy("Ollama", True, "start")

    texts = [lbl.text() for lbl in pill._popup_rows["Ollama"].findChildren(QLabel)]
    assert "Starting…" in texts


def test_a_format_no_engine_can_run_never_claims_an_engine_model(
    qtbot, monkeypatch, sample_specs, small_model
):
    """AWQ/GPTQ entries are not what a GGUF engine holds, so the app keeps them
    out of the installed-matching entirely — the AWQ row here shares every name
    token with the installed tag."""
    from providers import ProviderState, ProviderStatus

    monkeypatch.setattr(app_module, "UpdateChecker", _StubUpdateChecker)
    monkeypatch.setattr(app_module, "load_config", lambda: AppConfig(theme="dark"))
    monkeypatch.setattr(app_module, "save_config", lambda _cfg: None)
    monkeypatch.setattr(app_module.MainWindow, "_start_detection", lambda self: None)
    monkeypatch.setattr(app_module.MainWindow, "_apply_dwm_dark_title_bar", lambda self: None)
    window = app_module.MainWindow()
    qtbot.addWidget(window)

    gguf = _fit(small_model, sample_specs)
    awq_entry = _fit(
        LlmModel(name=small_model.name, provider="Somebody", format="awq"), sample_specs
    )
    window._fits = [gguf, awq_entry]
    status = ProviderStatus(
        name="Ollama",
        available=True,
        state=ProviderState.READY,
        # the id Ollama would actually hold for this catalog name
        installed_models={ollama_tag_candidates(small_model.name)[0]},
    )

    window._on_providers_detected([status])

    assert gguf.installed_providers == ["Ollama"]  # the names do line up
    assert awq_entry.installed_providers == []
    assert awq_entry.likely_providers == []


class TestCatalogDefaults:
    """What the catalog shows before the user touches anything."""

    def _proxy_with(self, fits):
        from widgets.model_table import ModelFilterProxy, ModelTableModel

        source = ModelTableModel()
        source.set_data(list(fits))
        proxy = ModelFilterProxy()
        proxy.setSourceModel(source)
        return source, proxy

    def _names(self, source, proxy):
        return sorted(
            source.get_fit(proxy.mapToSource(proxy.index(row, 0)).row()).model.name
            for row in range(proxy.rowCount())
        )

    def test_a_format_no_engine_can_load_is_hidden_by_default(
        self, qtbot, sample_specs, small_model
    ):
        gguf = _fit(small_model, sample_specs)
        awq = _fit(LlmModel(name="Awq-Only-7B", format="awq"), sample_specs)

        source, proxy = self._proxy_with([gguf, awq])

        assert self._names(source, proxy) == [small_model.name]

    def test_the_toggle_brings_them_back(self, qtbot, sample_specs, small_model):
        gguf = _fit(small_model, sample_specs)
        awq = _fit(LlmModel(name="Awq-Only-7B", format="awq"), sample_specs)
        source, proxy = self._proxy_with([gguf, awq])

        proxy.set_filters(runnable_only=False)

        assert self._names(source, proxy) == ["Awq-Only-7B", small_model.name]

    def test_a_typed_search_needs_every_word(self, qtbot, sample_specs):
        small = _fit(LlmModel(name="Qwen2.5-3B", format="gguf"), sample_specs)
        big = _fit(LlmModel(name="Qwen2.5-70B", format="gguf"), sample_specs)
        source, proxy = self._proxy_with([small, big])

        proxy.set_filters(search="qwen 3b")

        assert self._names(source, proxy) == ["Qwen2.5-3B"]


def test_the_filter_bar_starts_hiding_unrunnable_formats(qtbot):
    bar = FilterBar()
    qtbot.addWidget(bar)

    assert bar.runnable_only is True
    assert bar.get_filters()["runnable_only"] is True

    bar._runnable_checkbox.setChecked(False)
    assert bar.get_filters()["runnable_only"] is False

    bar.reset_filters()
    assert bar.runnable_only is True  # back to the default view


def test_the_filter_bar_restores_the_toggle_from_config(qtbot):
    bar = FilterBar()
    qtbot.addWidget(bar)

    bar.set_filters({"runnable_only": False})
    assert bar.runnable_only is False

    bar.set_filters({})  # an older config carries no such key
    assert bar.runnable_only is True
