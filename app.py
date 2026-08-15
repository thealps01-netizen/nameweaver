"""Nameweaver — LLM model fit analyzer. Main entry point."""

import ctypes
import logging
import platform
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QSize,
    QTimer,
    Qt,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta

from cfg import AppConfig, load_config, save_config, setup_logging
from dialogs import AboutDialog, AlertDialog
from hw import SystemSpecs
from models import (
    LlmModel,
    is_reupload,
    is_trusted_source,
    load_all_models,
    name_matches_installed,
)
from providers import ProviderState, ProviderStatus
from scoring import ModelFit, analyze_all
from themes import THEME_LABELS, generate_qss, get_theme
from updater import UpdateChecker, prompt_and_install
from version import __version__
from widgets.chat_dialog import ChatDialog
from widgets.comparison import ComparisonDialog
from widgets.detail_panel import DetailPanel
from widgets.download_dialog import (
    DownloadDialog,
    GgufMirrorPickerDialog,
    GgufPickerDialog,
)
from widgets.filter_bar import FilterBar
from widgets.hw_sim import HardwareSimPanel
from widgets.model_table import ModelFilterProxy, ModelTableModel, ModelTableView
from widgets.status_bar import AppStatusBar
from widgets.system_bar import SystemBar
from workers import (
    DownloadWorker,
    HardwareWorker,
    HFUpdateWorker,
    ProviderWorker,
    ScoringWorker,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Single-instance guard (Windows)
# ---------------------------------------------------------------------------

_mutex_handle = None


def _acquire_single_instance() -> bool:
    """Attempt to create a named mutex. Returns True if this is the first instance."""
    global _mutex_handle
    if platform.system() != "Windows":
        return True  # Only enforce on Windows
    try:
        kernel32 = ctypes.windll.kernel32
        _mutex_handle = kernel32.CreateMutexW(None, False, "Global\\NameweaverSingleInstance")
        last_error = kernel32.GetLastError()
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(_mutex_handle)
            _mutex_handle = None
            return False
        return True
    except Exception:
        return True  # Don't block if mutex fails


# ---------------------------------------------------------------------------
# Global crash handler
# ---------------------------------------------------------------------------


def _install_crash_handler():
    """Override sys.excepthook to log crashes and show a dialog."""
    original_hook = sys.excepthook

    def handler(exc_type, exc_value, exc_tb):
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("Unhandled exception:\n%s", tb_text)

        try:
            app = QApplication.instance()
            if app:
                QMessageBox.critical(
                    None,
                    "Nameweaver — Error",
                    f"An unexpected error occurred:\n\n{exc_value}\n\n"
                    f"Details have been written to the log file.",
                )
        except Exception:
            pass

        original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = handler


# ---------------------------------------------------------------------------
# DPI awareness
# ---------------------------------------------------------------------------


def _setup_dpi():
    """Enable Per-Monitor V2 DPI awareness on Windows."""
    if platform.system() == "Windows":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Custom painted widgets for frameless window
# ---------------------------------------------------------------------------


class _RoundedPanel(QWidget):
    """Rounded panel with border — works with WA_TranslucentBackground."""

    RADIUS = 14.0

    def __init__(self, parent=None, bg: str = "#1e1e2e", border: str = "#313244"):
        super().__init__(parent)
        self._bg = QColor(bg)
        self._border = QColor(border)

    def set_colors(self, bg: str, border: str):
        self._bg = QColor(bg)
        self._border = QColor(border)
        self.update()

    def paintEvent(self, _event):
        from PyQt6.QtCore import QRectF
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        p.fillPath(path, self._bg)
        pen = p.pen()
        pen.setColor(self._border)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)
        p.end()


class _GradientTitleBar(QWidget):
    """Title bar with a subtle gradient and rounded top corners."""

    def __init__(self, bg_start: str = "#1e1e2e", bg_end: str = "#181825",
                 border: str = "#313244", parent=None):
        super().__init__(parent)
        self._bg_start = bg_start
        self._bg_end = bg_end
        self._border = border

    def set_colors(self, bg_start: str, bg_end: str, border: str):
        self._bg_start = bg_start
        self._bg_end = bg_end
        self._border = border
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        R = _RoundedPanel.RADIUS

        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0, QColor(self._bg_start))
        grad.setColorAt(1.0, QColor(self._bg_end))

        # Rounded top corners, flat bottom
        path = QPainterPath()
        path.moveTo(R, 0)
        path.lineTo(self.width() - R, 0)
        path.quadTo(self.width(), 0, self.width(), R)
        path.lineTo(self.width(), self.height())
        path.lineTo(0, self.height())
        path.lineTo(0, R)
        path.quadTo(0, 0, R, 0)
        path.closeSubpath()

        p.fillPath(path, QBrush(grad))

        # Bottom border at bottom of header but start AFTER sidebar width
        pen = p.pen()
        pen.setColor(QColor(self._border))
        pen.setWidthF(1.0)
        p.setPen(pen)
        # Full width bottom border (like BitBuddy)
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


class _SidebarWidget(QWidget):
    """Custom-painted sidebar with rounded bottom-left corner and right border."""

    def __init__(self, bg: str = "#1e1e2e", border: str = "#313244", parent=None):
        super().__init__(parent)
        self._bg = QColor(bg)
        self._border = QColor(border)

    def set_colors(self, bg: str, border: str):
        self._bg = QColor(bg)
        self._border = QColor(border)
        self.update()

    def paintEvent(self, _event):
        from PyQt6.QtCore import QRectF
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        R = _RoundedPanel.RADIUS
        path = QPainterPath()
        path.moveTo(0, 0)
        path.lineTo(self.width(), 0)
        path.lineTo(self.width(), self.height())
        path.lineTo(R, self.height())
        path.quadTo(0, self.height(), 0, self.height() - R)
        path.lineTo(0, 0)
        path.closeSubpath()
        p.fillPath(path, self._bg)
        # Right border line
        pen = p.pen()
        pen.setColor(self._border)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        p.end()


def _gradient_sep(accent: str, border: str) -> QFrame:
    """BitBuddy-style gradient separator line."""
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setFixedHeight(1)
    sep.setStyleSheet(
        f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
        f"stop:0 {accent}, stop:0.4 {border}, stop:1 transparent);"
        f" border: none;"
    )
    return sep


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    """The central application window."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(800, 500)
        self._drag_pos = None

        # State
        self._config = load_config()
        self._models: list[LlmModel] = []
        self._specs: SystemSpecs | None = None
        self._providers: list[ProviderStatus] = []
        self._fits: list[ModelFit] = []


        # Workers
        self._hw_worker: HardwareWorker | None = None
        self._provider_worker: ProviderWorker | None = None
        self._provider_poller = None  # ProviderPoller — periodic state refresh
        self._provider_start_worker = None  # ProviderStartWorker — active start action
        self._provider_stop_worker = None   # ProviderStopWorker — active stop action
        self._scoring_worker: ScoringWorker | None = None
        self._hf_worker: HFUpdateWorker | None = None

        self._setup_ui()
        self._apply_theme(self._config.theme)
        self._restore_geometry()
        self._apply_dwm_dark_title_bar()

        # Remove default window icon — fully transparent
        transparent_pix = QPixmap(16, 16)
        transparent_pix.fill(QColor(0, 0, 0, 0))
        self.setWindowIcon(QIcon(transparent_pix))

        # Start background work
        QTimer.singleShot(100, self._start_detection)

        # Background update check (GitHub Releases). Kept on self so the
        # QThread is not garbage-collected while it runs.
        self._update_checker = UpdateChecker("thealps01-netizen", "nameweaver")
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.start()

    def _on_update_available(self, tag: str, url: str, notes: str) -> None:
        """A newer release exists — prompt the user to download & install."""
        logger.info("Update available: %s", tag)
        prompt_and_install(tag, url, notes, parent=self)

    # -----------------------------------------------------------------------
    # UI setup
    # -----------------------------------------------------------------------

    def _setup_ui(self):
        # Remove default toolbar / menu bar
        self.setMenuBar(None)

        central = QWidget()
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Rounded painted panel (like BitBuddy SPanel)
        tc = get_theme(self._config.theme)
        self._panel = _RoundedPanel(bg=tc.bg, border=tc.border)
        outer.addWidget(self._panel)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # Title bar (gradient, rounded top corners)
        self._title_bar = _GradientTitleBar(
            bg_start=tc.bg_alt, bg_end=tc.bg, border=tc.border
        )
        self._title_bar.setFixedHeight(52)
        header_layout = QHBoxLayout(self._title_bar)
        header_layout.setContentsMargins(18, 0, 10, 0)
        header_layout.setSpacing(10)

        # Icon + App name
        header_icon = QLabel()
        header_icon.setObjectName("header_icon")
        header_icon.setPixmap(qta.icon("mdi6.head-snowflake-outline", color=tc.accent).pixmap(QSize(36, 36)))
        header_icon.setFixedSize(40, 40)
        header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_icon.setStyleSheet("background: transparent;")
        header_layout.addWidget(header_icon)

        app_name_lbl = QLabel("Nameweaver")
        app_name_lbl.setObjectName("header_title")
        app_name_lbl.setStyleSheet(
            f"color: {tc.fg}; font: bold 13pt 'Segoe UI';"
            " background: transparent; letter-spacing: 1px;"
        )
        header_layout.addWidget(app_name_lbl)
        header_layout.addStretch()

        # Version badge (semi-transparent accent bg like BitBuddy)
        version_badge = QLabel(f"v{__version__}")
        version_badge.setObjectName("version_badge")
        version_badge.setStyleSheet(
            f"color: {tc.accent}; font: 8pt 'Segoe UI';"
            f" background: rgba({self._hex_to_rgb(tc.accent)},0.18);"
            f" border: 1px solid rgba({self._hex_to_rgb(tc.accent)},0.35);"
            " border-radius: 7px; padding: 1px 8px;"
        )
        header_layout.addWidget(version_badge)
        header_layout.addSpacing(6)

        # Minimize button (—)
        min_btn = QPushButton("—")
        min_btn.setObjectName("win_minimize_btn")
        min_btn.setFixedSize(34, 34)
        min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        min_btn.clicked.connect(self.showMinimized)
        header_layout.addWidget(min_btn)

        # Close button (×)
        close_btn = QPushButton("×")
        close_btn.setObjectName("win_close_btn")
        close_btn.setFixedSize(34, 34)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        header_layout.addWidget(close_btn)

        # Store for drag
        self._header_bar = self._title_bar

        panel_layout.addWidget(self._title_bar)
        
        # We need a horizontal layout that holds Sidebar AND the rest of the body (main+statusbar)
        body_outer_layout = QHBoxLayout()
        body_outer_layout.setContentsMargins(0, 0, 0, 0)
        body_outer_layout.setSpacing(0)
        panel_layout.addLayout(body_outer_layout, 1)

        # ── Left Sidebar (BitBuddy-style painted) ────────────────────
        sidebar = _SidebarWidget(bg=tc.bg_alt, border=tc.border)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(180)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 16, 10, 2)
        sidebar_layout.setSpacing(4)
        self._sidebar_widget = sidebar
        body_outer_layout.addWidget(sidebar)

        # ── Main Area (Content + Status bar at bottom) ───────────────
        main_col = QVBoxLayout()
        main_col.setContentsMargins(0, 0, 0, 0)
        main_col.setSpacing(0)
        body_outer_layout.addLayout(main_col, 1)

        main_area = QVBoxLayout()
        main_area.setContentsMargins(0, 0, 0, 0)
        main_area.setSpacing(0)
        
        root_layout = body_outer_layout # for status bar later if needed

        # Collect sidebar buttons for theme-aware icon refresh

        # Collect sidebar buttons for theme-aware icon refresh
        self._sidebar_btns: list[QPushButton] = []
        c = get_theme(self._config.theme)

        # Brand label (like BitBuddy)
        brand = QLabel("Nameweaver")
        brand.setObjectName("sidebar_brand")
        brand.setStyleSheet(
            f"color: {c.fg_muted}; font: bold 7pt 'Segoe UI';"
            " letter-spacing: 3px; background: transparent; padding-left: 6px;"
        )
        self._sidebar_brand = brand
        sidebar_layout.addWidget(brand)
        
        self._sidebar_brand_sep = _gradient_sep(c.accent, c.border)
        sidebar_layout.addWidget(self._sidebar_brand_sep)
        sidebar_layout.addSpacing(12)

        # Nav button helper (icon + text, like BitBuddy _NavButton)
        def _nav_btn(icon_name: str, label: str, checkable: bool = False) -> QPushButton:
            btn = QPushButton(f"  {label}")
            btn.setObjectName("sidebar_nav")
            btn.setIcon(qta.icon(icon_name, color=c.fg_muted))
            btn.setIconSize(QSize(32, 32))
            btn.setFixedHeight(48)
            btn.setCheckable(checkable)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("icon_name", icon_name)
            self._sidebar_btns.append(btn)
            return btn

        # Dashboard
        self._nav_dashboard_btn = _nav_btn("mdi6.view-dashboard-outline", "Dashboard")
        self._nav_dashboard_btn.clicked.connect(self._reset_to_dashboard)
        sidebar_layout.addWidget(self._nav_dashboard_btn)

        # Theme picker
        self._theme_btn = _nav_btn("mdi6.palette-outline", "Theme")
        self._theme_btn.clicked.connect(self._show_theme_picker)
        sidebar_layout.addWidget(self._theme_btn)

        # Update
        self._update_btn = _nav_btn("mdi6.cloud-download-outline", "Model Catalog")
        self._update_btn.clicked.connect(self._start_hf_update)
        sidebar_layout.addWidget(self._update_btn)

        # Compare
        self._compare_btn = _nav_btn("mdi6.scale-balance", "Compare")
        self._compare_btn.clicked.connect(self._open_comparison)
        sidebar_layout.addWidget(self._compare_btn)

        # HW Sim
        self._hwsim_btn = _nav_btn("mdi6.chip", "HW Sim", checkable=True)
        self._hwsim_btn.toggled.connect(self._toggle_hwsim)
        sidebar_layout.addWidget(self._hwsim_btn)

        sidebar_layout.addStretch()

        # About (bottom)
        about_btn = _nav_btn("mdi6.information-outline", "About")
        about_btn.clicked.connect(self._show_about)
        sidebar_layout.addWidget(about_btn)

        # ── Main Content Area ─────────────────────────────────────────

        # ── System Info Strip (below title bar) ──────────────────────
        # Section title row
        sys_title_row = QHBoxLayout()
        sys_title_row.setContentsMargins(0, 10, 0, 0)
        sys_title_row.setSpacing(8)
        sys_icon = QLabel()
        sys_icon.setPixmap(qta.icon("mdi6.monitor-dashboard", color=tc.accent).pixmap(QSize(22, 22)))
        sys_icon.setFixedSize(24, 24)
        sys_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sys_icon.setStyleSheet("background: transparent;")
        sys_icon.setObjectName("sys_title_icon")
        sys_title_row.addWidget(sys_icon)
        sys_title_lbl = QLabel("System Overview")
        sys_title_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {tc.fg_muted};"
            " letter-spacing: 1px; background: transparent;"
        )
        sys_title_lbl.setObjectName("sys_title_lbl")
        sys_title_row.addWidget(sys_title_lbl)
        sys_title_row.addStretch()

        # Add refresh button to the right of System Overview
        self._refresh_btn = QPushButton()
        self._refresh_btn.setFixedSize(28, 28)
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setIcon(qta.icon("mdi6.refresh", color=tc.fg_muted))
        self._refresh_btn.setIconSize(QSize(20, 20))
        self._refresh_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {tc.selection_bg}; }}"
        )
        self._refresh_btn.clicked.connect(self._start_detection)
        sys_title_row.addWidget(self._refresh_btn)

        sys_title_container = QHBoxLayout()
        sys_title_container.setContentsMargins(16, 0, 16, 0)
        sys_title_container.addLayout(sys_title_row)
        main_area.addLayout(sys_title_container)

        self._system_bar = SystemBar(theme_name=self._config.theme)
        self._system_bar.setObjectName("system_strip")
        self._system_bar.setFixedHeight(68)
        self._system_bar.gpu_selection_changed.connect(self._on_gpu_selection_changed)

        # Engine status pill — lives alongside the system bar
        from widgets.engine_status import EngineStatusPill
        self._engine_pill = EngineStatusPill(theme_name=self._config.theme)
        self._engine_pill.setFixedHeight(68)
        self._engine_pill.start_requested.connect(self._on_engine_start_requested)
        self._engine_pill.stop_requested.connect(self._on_engine_stop_requested)
        self._engine_pill.install_requested.connect(self._on_engine_install_requested)

        sys_bar_container = QHBoxLayout()
        sys_bar_container.setContentsMargins(16, 6, 16, 0)
        sys_bar_container.addWidget(self._system_bar, stretch=3)
        sys_bar_container.addWidget(self._engine_pill, stretch=1)
        main_area.addLayout(sys_bar_container)

        # Gradient separator after system bar
        sep1_container = QHBoxLayout()
        sep1_container.setContentsMargins(16, 12, 16, 0)
        self._sep1 = _gradient_sep(tc.accent, tc.border)
        sep1_container.addWidget(self._sep1)
        main_area.addLayout(sep1_container)

        # Scrollable body below header
        body = QVBoxLayout()
        body.setContentsMargins(16, 0, 16, 10)
        body.setSpacing(12)

        # ── Stat Cards Section ──────────────────────────────────────
        stats_section = QWidget()
        stats_section.setObjectName("section")
        stats_inner = QVBoxLayout(stats_section)
        stats_inner.setContentsMargins(0, 10, 0, 0)
        stats_inner.setSpacing(8)

        overview_title_row = QHBoxLayout()
        overview_title_row.setContentsMargins(0, 0, 0, 0)
        overview_title_row.setSpacing(8)
        
        overview_icon = QLabel()
        overview_icon.setObjectName("overview_icon")
        overview_icon.setPixmap(qta.icon("mdi6.chart-box-outline", color=tc.accent).pixmap(QSize(22, 22)))
        overview_icon.setFixedSize(24, 24)
        overview_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overview_title_row.addWidget(overview_icon)

        section_title = QLabel("Overview")
        section_title.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {tc.fg_muted};"
            " letter-spacing: 1px; background: transparent;"
        )
        overview_title_row.addWidget(section_title)
        overview_title_row.addStretch()
        
        stats_inner.addLayout(overview_title_row)

        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(10)

        self._stat_models = self._make_stat_card("Models", "0", "mdi6.package-variant")
        self._stat_score = self._make_stat_card("Avg Score", "—", "mdi6.star-outline")
        self._stat_gpu = self._make_stat_card("GPU Fit", "—", "mdi6.check-circle-outline")
        self._stat_providers = self._make_stat_card("Providers", "0", "mdi6.power-plug-outline")

        stats_row.addWidget(self._stat_models)
        stats_row.addWidget(self._stat_score)
        stats_row.addWidget(self._stat_gpu)
        stats_row.addWidget(self._stat_providers)

        stats_inner.addLayout(stats_row)
        body.addWidget(stats_section)

        # Gradient separator between stats and filter
        self._sep2 = _gradient_sep(tc.accent, tc.border)
        sep2_container = QHBoxLayout()
        sep2_container.setContentsMargins(0, 0, 0, 4)
        sep2_container.addWidget(self._sep2)
        body.addLayout(sep2_container)

        # ── Filter Section ───────────────────────────────────────────
        filter_section = QFrame()
        filter_section.setObjectName("filter_section")
        filter_inner = QVBoxLayout(filter_section)
        filter_inner.setContentsMargins(0, 0, 0, 0)
        filter_inner.setSpacing(0)

        self._filter_bar = FilterBar()
        self._filter_bar.filters_changed.connect(self._apply_filters)
        self._filter_bar.preference_changed.connect(self._on_preference_changed)
        # Restore persisted preference before signals start firing
        self._filter_bar.set_score_preference(self._config.score_preference)
        filter_inner.addWidget(self._filter_bar)
        
        # We need a small margin container so it aligns with models box horizontally
        filter_container = QHBoxLayout()
        filter_container.setContentsMargins(0, 6, 0, 0)
        filter_container.addWidget(filter_section)
        body.addLayout(filter_container)

        # ── Content: Table + Detail + HW Sim ─────────────────────────
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        # Model table in a card frame
        table_card = QFrame()
        table_card.setObjectName("card")
        table_card_layout = QVBoxLayout(table_card)
        table_card_layout.setContentsMargins(0, 0, 0, 0)
        table_card_layout.setSpacing(0)

        self._table_model = ModelTableModel()
        self._filter_proxy = ModelFilterProxy()
        self._filter_proxy.setSourceModel(self._table_model)
        self._table_view = ModelTableView()
        self._table_view.setModel(self._filter_proxy)
        self._table_view.model_selected.connect(self._on_model_selected)
        self._table_view.download_requested.connect(self._on_download_requested)
        self._table_view.run_requested.connect(self._on_run_requested)
        self._table_view.set_default_column_widths()
        table_card_layout.addWidget(self._table_view)
        content_layout.addWidget(table_card, stretch=1)

        # Detail panel in a card frame — hidden until a model is selected
        self._detail_card = QFrame()
        self._detail_card.setObjectName("card")
        self._detail_card.setVisible(False)
        self._detail_card.setProperty("_target_width", 340)
        detail_card_layout = QVBoxLayout(self._detail_card)
        detail_card_layout.setContentsMargins(0, 0, 0, 0)
        detail_card_layout.setSpacing(0)

        self._detail_panel = DetailPanel()
        self._detail_panel.download_requested.connect(self._on_download_requested)
        self._detail_panel.run_requested.connect(self._on_run_requested)
        detail_card_layout.addWidget(self._detail_panel)
        content_layout.addWidget(self._detail_card)

        # HW sim panel (hidden by default)
        self._hwsim_panel = HardwareSimPanel()
        self._hwsim_panel.simulation_changed.connect(self._on_hw_sim_changed)
        self._hwsim_panel.set_theme(self._config.theme)
        self._hwsim_panel.setVisible(False)
        self._hwsim_panel.setProperty("_target_width", 240)
        self._hwsim_panel.setObjectName("card")
        content_layout.addWidget(self._hwsim_panel)

        body.addLayout(content_layout, stretch=1)
        main_area.addLayout(body, stretch=1)

        # Collect animated sections for startup effect
        self._anim_widgets = [
            stats_section, filter_section,
        ]

        main_col.addLayout(main_area, stretch=1)

        # ── Status Bar (bottom strip of main_col) ────────────────────
        self._status_bar = AppStatusBar()
        self._status_bar.set_version(__version__)
        self._status_bar.set_theme_name(self._config.theme)

        main_col.addWidget(self._status_bar)

    # -----------------------------------------------------------------------
    # Stat cards
    # -----------------------------------------------------------------------

    def _make_stat_card(self, title: str, value: str, icon_name: str) -> QFrame:
        card = QFrame()
        card.setObjectName("stat_card")
        card.setFixedHeight(68)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        c = get_theme(self._config.theme)
        icon_label = QLabel()
        icon_label.setObjectName("stat_icon")
        icon_label.setPixmap(qta.icon(icon_name, color=c.accent).pixmap(QSize(24, 24)))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedSize(32, 32)
        icon_label.setProperty("icon_name", icon_name)
        layout.addWidget(icon_label)

        text_area = QVBoxLayout()
        text_area.setSpacing(0)
        value_label = QLabel(value)
        value_label.setObjectName("stat_value")
        text_area.addWidget(value_label)
        title_label = QLabel(title)
        title_label.setObjectName("stat_title")
        text_area.addWidget(title_label)
        layout.addLayout(text_area)
        layout.addStretch()

        return card

    def _update_stat_cards(self):
        """Refresh stat card values from current data."""
        # Models count
        total = len(self._fits)
        val = self._stat_models.findChild(QLabel, "stat_value")
        if val:
            val.setText(str(total))

        # Average score
        if self._fits:
            avg = sum(f.score for f in self._fits) / len(self._fits)
            val = self._stat_score.findChild(QLabel, "stat_value")
            if val:
                val.setText(f"{avg:.1f}")
        
        # GPU fit count
        from scoring import FitLevel
        gpu_fit = sum(1 for f in self._fits if f.fit_level in (FitLevel.PERFECT, FitLevel.GOOD))
        val = self._stat_gpu.findChild(QLabel, "stat_value")
        if val:
            val.setText(str(gpu_fit))

        # Providers
        available = sum(1 for p in self._providers if p.available)
        val = self._stat_providers.findChild(QLabel, "stat_value")
        if val:
            val.setText(str(available))

    # -----------------------------------------------------------------------
    # Frameless window drag & maximize
    # -----------------------------------------------------------------------

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> str:
        """Convert '#aabbcc' to 'r,g,b' string for rgba()."""
        h = hex_color.lstrip("#")
        return f"{int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)}"

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Only drag from title bar area
            local = self._header_bar.mapFromGlobal(event.globalPosition().toPoint())
            if self._header_bar.rect().contains(local):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            if self.isMaximized():
                self.showNormal()
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        local = self._header_bar.mapFromGlobal(event.globalPosition().toPoint())
        if self._header_bar.rect().contains(local):
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)

    def _apply_dwm_dark_title_bar(self):
        """Use Windows DWM API to style the frameless window."""
        if platform.system() != "Windows":
            return
        try:
            hwnd = int(self.winId())
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(value), ctypes.sizeof(value),
            )
            # Set caption color to match theme bg
            colors = get_theme(self._config.theme)
            self._set_title_bar_color(colors.bg)

            # Set window border color to match theme
            h = colors.border.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            DWMWA_BORDER_COLOR = 34
            border_ref = ctypes.c_int(r | (g << 8) | (b << 16))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_BORDER_COLOR,
                ctypes.byref(border_ref), ctypes.sizeof(border_ref),
            )

            # Request rounded corners (Windows 11)
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(DWMWCP_ROUND), ctypes.sizeof(DWMWCP_ROUND),
            )
        except Exception:
            pass

    def _set_title_bar_color(self, hex_color: str):
        """Set Windows title bar caption color via DWM."""
        if platform.system() != "Windows":
            return
        try:
            hwnd = int(self.winId())
            DWMWA_CAPTION_COLOR = 35
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            # COLORREF = 0x00BBGGRR
            colorref = ctypes.c_int(r | (g << 8) | (b << 16))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_CAPTION_COLOR,
                ctypes.byref(colorref), ctypes.sizeof(colorref),
            )
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Animations
    # -----------------------------------------------------------------------

    def _animate_panel_show(self, widget, show: bool, axis: str = "height"):
        """Slide a panel open/closed. axis='width' for horizontal panels."""
        prop = b"maximumWidth" if axis == "width" else b"maximumHeight"
        QWIDGETSIZE_MAX = 16777215

        if show:
            if axis == "width":
                target = widget.property("_target_width") or widget.sizeHint().width() or 280
            else:
                target = widget.sizeHint().height() or 300
            if axis == "width":
                widget.setMaximumWidth(0)
            else:
                widget.setMaximumHeight(0)
            widget.setVisible(True)
            anim = QPropertyAnimation(widget, prop)
            anim.setStartValue(0)
            anim.setEndValue(target)
            anim.setDuration(400)
            anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            if axis == "width":
                anim.finished.connect(lambda: widget.setMaximumWidth(QWIDGETSIZE_MAX))
            else:
                anim.finished.connect(lambda: widget.setMaximumHeight(QWIDGETSIZE_MAX))
        else:
            current = widget.width() if axis == "width" else widget.height()
            anim = QPropertyAnimation(widget, prop)
            anim.setStartValue(current)
            anim.setEndValue(0)
            anim.setDuration(300)
            anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            anim.finished.connect(lambda: widget.setVisible(False))

        widget._panel_anim = anim
        anim.start()

    # -----------------------------------------------------------------------
    # Theme
    # -----------------------------------------------------------------------

    def _theme_label(self, theme_key: str) -> str:
        return THEME_LABELS.get(theme_key, theme_key.title())

    def _apply_theme(self, theme_name: str):
        colors = get_theme(theme_name)
        qss = generate_qss(colors)
        QApplication.instance().setStyleSheet(qss)
        self._table_model.set_theme(theme_name)
        self._detail_panel.set_theme(theme_name)
        self._status_bar.set_theme_name(theme_name)
        self._system_bar.refresh_theme(theme_name)
        if hasattr(self, "_engine_pill"):
            self._engine_pill.refresh_theme(theme_name)
        if self._providers:
            self._system_bar.update_providers(self._providers, theme_name)

        # Update painted panel & title bar colors
        self._panel.set_colors(colors.bg, colors.border)
        self._title_bar.set_colors(colors.bg_alt, colors.bg, colors.border)
        if hasattr(self, '_sidebar_widget'):
            self._sidebar_widget.set_colors(colors.bg_alt, colors.border)

        if hasattr(self, '_sep1'):
            self._sep1.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 {colors.accent}, stop:0.4 {colors.border}, stop:1 transparent);"
                f" border: none;"
            )
        if hasattr(self, '_sep2'):
            self._sep2.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 {colors.accent}, stop:0.4 {colors.border}, stop:1 transparent);"
                f" border: none;"
            )
        if hasattr(self, '_sidebar_brand_sep'):
            self._sidebar_brand_sep.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                f"stop:0 {colors.accent}, stop:0.4 {colors.border}, stop:1 transparent);"
                f" border: none;"
            )

        # Title bar text + badge
        title_lbl = self._header_bar.findChild(QLabel, "header_title")
        if title_lbl:
            title_lbl.setStyleSheet(
                f"color: {colors.fg}; font: bold 13pt 'Segoe UI';"
                " background: transparent; letter-spacing: 1px;"
            )
        badge = self._header_bar.findChild(QLabel, "version_badge")
        if badge:
            rgb = self._hex_to_rgb(colors.accent)
            badge.setStyleSheet(
                f"color: {colors.accent}; font: 8pt 'Segoe UI';"
                f" background: rgba({rgb},0.18);"
                f" border: 1px solid rgba({rgb},0.35);"
                " border-radius: 7px; padding: 1px 8px;"
            )

        # DWM
        is_dark = theme_name != "light"
        try:
            hwnd = int(self.winId())
            val = ctypes.c_int(1 if is_dark else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(val), ctypes.sizeof(val),
            )
        except Exception:
            pass
        self._set_title_bar_color(colors.bg)

        # Refresh header icon
        header_icon = self._header_bar.findChild(QLabel, "header_icon")
        if header_icon:
            header_icon.setPixmap(qta.icon("mdi6.head-snowflake-outline", color=colors.accent).pixmap(QSize(36, 36)))

        # Refresh sidebar icons with new theme colors
        # Refresh sidebar nav button icons
        for btn in self._sidebar_btns:
            icon_name = btn.property("icon_name")
            if icon_name:
                is_active = btn.isChecked()
                color = colors.accent if is_active else colors.fg_muted
                btn.setIcon(qta.icon(icon_name, color=color))

        # Refresh sidebar brand label
        self._sidebar_brand.setStyleSheet(
            f"color: {colors.fg_muted}; font: bold 7pt 'Segoe UI';"
            " letter-spacing: 3px; background: transparent; padding-left: 6px;"
        )

        # Refresh system overview title
        sys_icon = self.findChild(QLabel, "sys_title_icon")
        if sys_icon:
            sys_icon.setPixmap(qta.icon("mdi6.monitor-dashboard", color=colors.accent).pixmap(QSize(22, 22)))
        sys_lbl = self.findChild(QLabel, "sys_title_lbl")
        if sys_lbl:
            sys_lbl.setStyleSheet(
                f"font-size: 12px; font-weight: 700; color: {colors.fg_muted};"
                " letter-spacing: 1px; background: transparent;"
            )

        overview_icon = self.findChild(QLabel, "overview_icon")
        if overview_icon:
            overview_icon.setPixmap(qta.icon("mdi6.chart-box-outline", color=colors.accent).pixmap(QSize(22, 22)))

        # Refresh stat card icons
        for card in (self._stat_models, self._stat_score, self._stat_gpu, self._stat_providers):
            icon_lbl = card.findChild(QLabel, "stat_icon")
            if icon_lbl:
                icon_name = icon_lbl.property("icon_name")
                if icon_name:
                    icon_lbl.setPixmap(qta.icon(icon_name, color=colors.accent).pixmap(QSize(24, 24)))

        # Refresh button in system bar
        if hasattr(self, '_refresh_btn'):
            self._refresh_btn.setIcon(qta.icon("mdi6.refresh", color=colors.fg_muted))

    def _set_theme(self, theme_name: str):
        """Apply + persist a theme selection from the dropdown."""
        if theme_name == self._config.theme:
            return
        self._config.theme = theme_name
        QTimer.singleShot(0, lambda: self._apply_theme(theme_name))
        self._save_config()

        # Update check marks in picker if open
        if hasattr(self, '_theme_picker') and self._theme_picker.isVisible():
            self._theme_picker.hide()
            
        # Update hw_sim icons
        if hasattr(self, '_hwsim_panel'):
            self._hwsim_panel.set_theme(theme_name)

    def _show_theme_picker(self):
        """Show a custom theme picker flyout next to the sidebar."""
        if hasattr(self, '_theme_picker') and self._theme_picker.isVisible():
            self._theme_picker.hide()
            return

        c = get_theme(self._config.theme)
        _ah = c.accent.lstrip("#")
        _ar, _ag, _ab = int(_ah[0:2], 16), int(_ah[2:4], 16), int(_ah[4:6], 16)

        picker = QFrame(self)
        picker.setObjectName("theme_picker")
        picker.setFixedWidth(250)
        picker.setStyleSheet(
            f"QFrame#theme_picker {{ background: {c.bg}; border: 1px solid {c.accent};"
            f" border-radius: 12px; }}"
        )

        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect(picker)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 2)
        _sc = QColor(c.accent)
        _sc.setAlpha(60)
        shadow.setColor(_sc)
        picker.setGraphicsEffect(shadow)

        layout = QVBoxLayout(picker)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(4)

        # Title row with icon
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_icon = QLabel()
        title_icon.setPixmap(
            qta.icon("mdi6.palette-outline", color=c.accent).pixmap(QSize(28, 28))
        )
        title_icon.setFixedSize(32, 32)
        title_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_icon.setStyleSheet("background: transparent;")
        title_row.addWidget(title_icon)
        title = QLabel("Themes")
        title.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {c.fg}; background: transparent;"
        )
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)
        layout.addSpacing(8)

        # Theme icons map
        THEME_ICONS = {
            "dark": "mdi6.weather-night",
            "light": "mdi6.weather-sunny",
            "dracula": "mdi6.bat",
            "nord": "mdi6.snowflake",
            "gruvbox": "mdi6.coffee",
            "solarized": "mdi6.white-balance-sunny",
        }

        for theme_key, label in THEME_LABELS.items():
            tc = get_theme(theme_key)
            is_current = theme_key == self._config.theme

            btn = QFrame()
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setObjectName("theme_choice_card")

            if is_current:
                btn.setStyleSheet(
                    f"QFrame#theme_choice_card {{ background: {tc.accent}; border-radius: 8px; }}"
                    f"QFrame#theme_choice_card QLabel {{ color: {tc.accent_text}; background: transparent; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QFrame#theme_choice_card {{ background: transparent; border-radius: 8px; }}"
                    f"QFrame#theme_choice_card:hover {{ background: {c.selection_bg}; }}"
                    f"QFrame#theme_choice_card QLabel {{ color: {c.fg}; background: transparent; }}"
                )

            btn_layout = QHBoxLayout(btn)
            btn_layout.setContentsMargins(10, 7, 10, 7)
            btn_layout.setSpacing(10)

            # Theme icon
            icon_color = tc.accent_text if is_current else tc.accent
            icon_lbl = QLabel()
            icon_name = THEME_ICONS.get(theme_key, "mdi6.palette")
            icon_lbl.setPixmap(
                qta.icon(icon_name, color=icon_color).pixmap(QSize(28, 28))
            )
            icon_lbl.setFixedSize(32, 32)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn_layout.addWidget(icon_lbl)

            # Theme name
            name_lbl = QLabel(label)
            name_lbl.setStyleSheet(
                f"font-size: 13px; font-weight: {'700' if is_current else '400'};"
            )
            btn_layout.addWidget(name_lbl, stretch=1)

            # Checkmark for current
            if is_current:
                check_lbl = QLabel()
                check_lbl.setPixmap(
                    qta.icon("mdi6.check", color=tc.accent_text).pixmap(QSize(24, 24))
                )
                check_lbl.setFixedSize(24, 24)
                btn_layout.addWidget(check_lbl)

            # Click handler via mousePressEvent override
            btn.mousePressEvent = lambda _, k=theme_key: self._set_theme(k)
            layout.addWidget(btn)

        layout.addStretch()
        self._theme_picker = picker

        # Position: start from the right edge of sidebar + line
        sidebar = self.findChild(QFrame, "sidebar")
        sidebar_width = sidebar.width() if sidebar else 72
        target_height = min(380, 70 + len(THEME_LABELS) * 46)
        picker.setFixedHeight(target_height)
        
        # Calculate precise Y relative to window
        btn_local_y = self._theme_btn.y()
        target_x = sidebar_width + 1
        target_y = btn_local_y

        # Start flush with sidebar edge
        picker.move(target_x, target_y)
        picker.show()
        picker.raise_()

        # Slide animation (short scale for smoothness instead of position if possible, 
        # but requested "starts right after the line" so we just set position exactly
        anim = QPropertyAnimation(picker, b"pos", picker)
        anim.setStartValue(QPoint(target_x, target_y - 10))
        anim.setEndValue(QPoint(target_x, target_y))
        anim.setDuration(150)
        anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._theme_picker_anim = anim
        anim.start()

    # -----------------------------------------------------------------------
    # Refresh spin animation (qtawesome built-in)
    # -----------------------------------------------------------------------

    def _start_refresh_spin(self):
        """Start spinning the refresh button icon using qtawesome Spin."""
        colors = get_theme(self._config.theme)
        if not hasattr(self, '_spin_anim'):
            self._spin_anim = qta.Spin(self._refresh_btn, interval=30, step=15)
        spin_icon = qta.icon(
            "mdi6.refresh", color=colors.accent,
            animation=self._spin_anim,
        )
        self._refresh_btn.setIcon(spin_icon)
        self._refresh_btn.setIconSize(QSize(20, 20))
        self._spin_anim.start()

    def _stop_refresh_spin(self):
        """Stop the spin and reset to normal icon."""
        if hasattr(self, '_spin_anim'):
            self._spin_anim.stop()
        colors = get_theme(self._config.theme)
        self._refresh_btn.setIcon(
            qta.icon("mdi6.refresh", color=colors.fg_muted)
        )

    # -----------------------------------------------------------------------
    # Detection & scoring pipeline
    # -----------------------------------------------------------------------

    def _start_detection(self):
        """Kick off hardware + provider detection in background threads."""
        # Start refresh spin animation
        self._start_refresh_spin()

        # Load models synchronously (embedded + HF cache merged)
        self._models = load_all_models()
        providers = sorted(set(m.provider for m in self._models))
        self._filter_bar.populate_providers(providers)
        self._filter_bar.populate_quants(
            sorted(set(m.quantization for m in self._models if m.quantization))
        )
        self._filter_bar.populate_licenses(
            sorted(set(m.license for m in self._models if m.license))
        )
        # Restore saved filter selections
        if self._config.filters:
            self._filter_bar.set_filters(self._config.filters)

        # Hardware detection
        self._hw_worker = HardwareWorker()
        self._hw_worker.finished.connect(self._on_hardware_detected)
        self._hw_worker.error.connect(lambda e: logger.error("HW detection error: %s", e))
        self._hw_worker.start()

        # Provider detection (one-shot, quickly populates initial state)
        self._provider_worker = ProviderWorker()
        self._provider_worker.finished.connect(self._on_providers_detected)
        self._provider_worker.error.connect(lambda e: logger.error("Provider error: %s", e))
        self._provider_worker.start()

        # Periodic poller — keeps engine pill live while user leaves the app
        # running and starts/stops Ollama or LM Studio in the background.
        if not hasattr(self, "_provider_poller") or self._provider_poller is None:
            from workers import ProviderPoller
            self._provider_poller = ProviderPoller(interval_seconds=10)
            self._provider_poller.status_changed.connect(self._on_providers_detected)
            self._provider_poller.start()

    def _on_hardware_detected(self, specs: SystemSpecs):
        """Called when hardware detection completes."""
        # Apply persisted per-GPU disable list (from user's last session)
        from hw import apply_disabled_list
        apply_disabled_list(specs, self._config.disabled_gpus)
        specs.total_gpu_vram_gb = sum(g.vram_gb for g in specs.gpus if g.enabled)
        self._specs = specs
        self._system_bar.update_hardware(specs)
        self._hwsim_panel.set_real_specs(specs)
        logger.info(
            "Hardware: %s, RAM=%.1f GB, GPU=%s (%.1f GB VRAM, %d/%d enabled)",
            specs.cpu_name, specs.total_ram_gb, specs.gpu_name,
            specs.total_gpu_vram_gb,
            sum(1 for g in specs.gpus if g.enabled), len(specs.gpus),
        )
        self._start_scoring(specs)

    def _on_gpu_selection_changed(self, active_names: list):
        """User toggled GPU checkboxes in the system-bar popup — re-score."""
        if self._specs is None:
            return
        disabled = [g.name for g in self._specs.gpus if g.name not in active_names]
        self._config.disabled_gpus = disabled
        try:
            save_config(self._config)
        except Exception as exc:
            logger.warning("Could not persist disabled_gpus: %s", exc)
        for g in self._specs.gpus:
            g.enabled = g.name in active_names
        self._specs.total_gpu_vram_gb = sum(
            g.vram_gb for g in self._specs.gpus if g.enabled
        )
        # Re-score with the new effective VRAM/bandwidth
        self._start_scoring(self._specs)

    def _on_providers_detected(self, providers: list[ProviderStatus]):
        """Called when provider detection completes."""
        self._providers = providers
        self._system_bar.update_providers(providers, self._config.theme)
        if hasattr(self, "_engine_pill"):
            self._engine_pill.update_status(providers)
        available = [p for p in providers if p.available]
        logger.info("Providers: %d available (%s)", len(available), ", ".join(p.name for p in available))

        # Mark installed models
        installed_names = set()
        for p in providers:
            installed_names.update(p.installed_models)

        for fit in self._fits:
            fit.installed = name_matches_installed(fit.model.name, installed_names)

        # Refresh table if scoring is already done
        if self._fits:
            self._table_model.set_data(self._fits)

        self._update_stat_cards()

    # ------------------------------------------------------------------
    # Engine lifecycle handlers (start / install from pill widget)
    # ------------------------------------------------------------------

    def _on_engine_start_requested(self, action_key: str):
        """Pill asked us to start an installed-but-off provider."""
        if self._provider_start_worker and self._provider_start_worker.isRunning():
            return  # Already trying

        from workers import ProviderStartWorker
        self._provider_start_worker = ProviderStartWorker(action_key)
        self._provider_start_worker.finished.connect(
            lambda ok: self._on_engine_start_finished(action_key, ok)
        )
        self._provider_start_worker.error.connect(
            lambda e, k=action_key: (
                logger.error("Engine start error: %s", e),
                self._clear_engine_busy(k),
            )
        )
        self._provider_start_worker.start()

        # Give the user immediate feedback — pill will update on next poll
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

    _ACTION_TO_PROVIDER = {
        "start_ollama": "Ollama", "stop_ollama": "Ollama",
        "start_lmstudio": "LM Studio", "stop_lmstudio": "LM Studio",
        "start_dmr": "Docker Model Runner", "stop_dmr": "Docker Model Runner",
    }

    def _clear_engine_busy(self, action_key: str) -> None:
        name = self._ACTION_TO_PROVIDER.get(action_key)
        if name and hasattr(self, "_engine_pill"):
            self._engine_pill.set_provider_busy(name, False)

    def _on_engine_start_finished(self, action_key: str, ok: bool):
        """Refresh state after a start attempt so the pill goes green (or stays yellow)."""
        # Don't clear busy here on success — let `update_status` clear it when
        # the fresh detection confirms the state transition (avoids flicker).
        # On failure the state won't change, so we clear manually below.
        if ok:
            logger.info("Engine start (%s) succeeded", action_key)
        else:
            self._clear_engine_busy(action_key)
            logger.warning("Engine start (%s) failed — showing guide", action_key)
            # LM Studio has no CLI fallback → show guided modal
            if action_key == "start_lmstudio":
                from provider_control import open_lmstudio_app
                open_lmstudio_app()
                QMessageBox.information(
                    self,
                    "Opening LM Studio",
                    "The LM Studio window is now open. Please follow these steps:\n\n"
                    "1. Open the 'Developer' tab from the left menu\n"
                    "2. Press the 'Start Server' button\n\n"
                    "You don't need to close this app — I'll detect the server "
                    "automatically as soon as it starts.",
                )
            elif action_key == "start_ollama":
                QMessageBox.warning(
                    self,
                    "Failed to start Ollama",
                    "The Ollama service could not be started. Please start "
                    "the Ollama app manually or try reinstalling it.",
                )

        # Trigger an immediate refresh rather than waiting 10 s
        self._refresh_providers()

    def _on_engine_stop_requested(self, action_key: str):
        """Pill asked us to stop a running provider."""
        if self._provider_stop_worker and self._provider_stop_worker.isRunning():
            return

        # DMR has no automatic stop — guide the user
        if action_key == "stop_dmr":
            QMessageBox.information(
                self,
                "Docker Model Runner",
                "To stop Docker Model Runner, open Docker Desktop and "
                "disable the 'Model Runner' feature under Settings > Beta features.",
            )
            return

        from workers import ProviderStopWorker
        self._provider_stop_worker = ProviderStopWorker(action_key)
        self._provider_stop_worker.finished.connect(
            lambda ok: self._on_engine_stop_finished(action_key, ok)
        )
        self._provider_stop_worker.error.connect(
            lambda e, k=action_key: (
                logger.error("Engine stop error: %s", e),
                self._clear_engine_busy(k),
            )
        )
        self._provider_stop_worker.start()

    def _on_engine_stop_finished(self, action_key: str, ok: bool):
        """Refresh after a stop attempt.

        Don't clear busy on success — let ``update_status`` clear it when the
        fresh detection confirms READY → INSTALLED_OFF, so the pill doesn't
        flicker green for a beat between "worker done" and "new state in".
        """
        if ok:
            logger.info("Engine stop (%s) succeeded", action_key)
        else:
            self._clear_engine_busy(action_key)
            logger.warning("Engine stop (%s) failed", action_key)
            if action_key == "stop_lmstudio":
                QMessageBox.warning(
                    self,
                    "Failed to stop LM Studio",
                    "The LM Studio server could not be stopped automatically. "
                    "Please press the 'Stop Server' button in the app.",
                )
            elif action_key == "stop_ollama":
                QMessageBox.warning(
                    self,
                    "Failed to stop Ollama",
                    "The Ollama service could not be stopped. You can end "
                    "the 'ollama.exe' process manually from Task Manager.",
                )

        self._refresh_providers()

    def _on_engine_install_requested(self, provider_name: str):
        """Pill asked us to install a missing provider."""
        from provider_control import (
            open_installer_page,
            suggested_install_command,
        )

        cmd = suggested_install_command(provider_name)
        msg = (
            f"<b>{provider_name}</b> is not installed.<br><br>"
            f"Should I open the official download page in your browser?"
        )
        if cmd and not cmd.startswith("http"):
            msg += (
                f"<br><br>Or you can run this command in your terminal:"
                f"<br><code>{cmd}</code>"
            )

        reply = QMessageBox.question(
            self,
            f"Install {provider_name}",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            open_installer_page(provider_name)

    def _start_scoring(self, specs: SystemSpecs):
        """Score all models against hardware."""
        if not self._models:
            return

        self._scoring_worker = ScoringWorker(
            self._models,
            specs,
            preference=self._config.score_preference,
        )
        self._scoring_worker.finished.connect(self._on_scoring_complete)
        self._scoring_worker.error.connect(lambda e: logger.error("Scoring error: %s", e))
        self._scoring_worker.start()

    def _on_scoring_complete(self, fits: list[ModelFit]):
        """Called when scoring finishes."""
        self._fits = fits
        self._table_model.set_data(fits)
        self._status_bar.set_model_count(len(fits))
        self._table_view.sortByColumn(3, Qt.SortOrder.DescendingOrder)  # Score column
        self._update_stat_cards()
        self._stop_refresh_spin()
        logger.info("Scored %d models", len(fits))

    def _on_preference_changed(self, preference: float) -> None:
        """Slider moved: re-bias stored fits without re-analyzing.

        Uses ``apply_preference`` which only recomputes composite scores
        from ``score_components`` — ~200× faster than a full re-analyze.
        """
        self._config.score_preference = preference
        try:
            save_config(self._config)
        except Exception as exc:
            logger.warning("Could not persist score_preference: %s", exc)

        if not self._fits:
            return
        from scoring import apply_preference, rank_models

        apply_preference(self._fits, preference)
        self._fits = rank_models(self._fits)
        self._table_model.set_data(self._fits)
        self._update_stat_cards()

    # -----------------------------------------------------------------------
    # HuggingFace update
    # -----------------------------------------------------------------------

    def _start_hf_update(self):
        """Fetch latest models from HuggingFace in the background."""
        if self._hf_worker and self._hf_worker.isRunning():
            QMessageBox.information(
                self,
                "Update in progress",
                "A HuggingFace update is already running.",
            )
            return

        self._update_btn.setEnabled(False)
        self._update_btn.setToolTip("Updating…")
        self._status_bar.showMessage("Fetching models from HuggingFace…")
        self._start_refresh_spin()

        self._hf_worker = HFUpdateWorker(
            token=self._config.hf_token,
            limit=200,
            fetch_config=False,
        )
        self._hf_worker.progress.connect(self._on_hf_progress)
        self._hf_worker.finished.connect(self._on_hf_finished)
        self._hf_worker.error.connect(self._on_hf_error)
        self._hf_worker.start()

    def _on_hf_progress(self, pct: int, msg: str):
        self._status_bar.showMessage(f"HuggingFace: {msg} ({pct}%)")

    def _on_hf_finished(self, models: list):
        from datetime import datetime, timezone

        self._update_btn.setEnabled(True)
        self._update_btn.setToolTip("Fetch models from HuggingFace")

        delta = len(models) - len(self._models)
        self._models = models
        self._config.last_hf_update = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._save_config()

        # Refresh provider list in filter bar
        providers = sorted(set(m.provider for m in self._models))
        self._filter_bar.populate_providers(providers)

        # Re-score with new catalog
        if self._specs:
            self._start_scoring(self._specs)

        msg = (
            f"HuggingFace update complete: {len(self._models)} models total"
            + (f" (+{delta} new)" if delta > 0 else "")
        )
        self._status_bar.showMessage(msg, 5000)
        logger.info(msg)
        self._stop_refresh_spin()

    def _on_hf_error(self, err: str):
        self._update_btn.setEnabled(True)
        self._update_btn.setToolTip("Fetch models from HuggingFace")
        self._status_bar.showMessage("HuggingFace update failed", 5000)
        self._stop_refresh_spin()
        QMessageBox.warning(
            self,
            "HuggingFace update failed",
            f"Could not fetch models from HuggingFace:\n\n{err}\n\n"
            "Check your internet connection and HF_TOKEN if configured.",
        )

    # -----------------------------------------------------------------------
    # Filters
    # -----------------------------------------------------------------------

    def _apply_filters(self):
        fb = self._filter_bar
        self._filter_proxy.set_filters(
            search=fb.search_text,
            provider=fb.provider_filter,
            usecase=fb.usecase_filter,
            fit=fb.fit_filter,
            comfort=fb.comfort_filter,
            quant=fb.quant_filter,
            license=fb.license_filter,
            capability=fb.capability_filter,
            installed_only=fb.installed_only,
            min_tps=fb.min_tps,
        )
        visible = self._filter_proxy.rowCount()
        self._status_bar.set_model_count(len(self._fits), visible)

    def _reset_to_dashboard(self):
        """Reset filters, clear selection, scroll to top."""
        self._filter_bar.reset_filters()
        self._table_view.clearSelection()
        self._table_view.scrollToTop()
        if self._detail_card.isVisible():
            self._animate_panel_show(self._detail_card, False, axis="width")

    # -----------------------------------------------------------------------
    # Model selection
    # -----------------------------------------------------------------------

    def _on_model_selected(self, fit: ModelFit | None):
        self._detail_panel.show_model(fit)
        if fit is not None and not self._detail_card.isVisible():
            self._animate_panel_show(self._detail_card, True, axis="width")
        elif fit is None and self._detail_card.isVisible():
            self._animate_panel_show(self._detail_card, False, axis="width")

    # -----------------------------------------------------------------------
    # Download / Run actions
    # -----------------------------------------------------------------------

    def _pick_ollama_candidate(self, model_name: str) -> str | None:
        """Guess an Ollama tag from a HuggingFace-style model name."""
        # Heuristic: "Llama-3.1-8B-Instruct" → "llama3.1:8b-instruct"
        # Fallback: use the first segment lowercased.
        name = model_name.lower()
        # Strip common suffixes
        name = name.replace("_", "-")
        return name  # Let Ollama resolve; it'll error if unknown

    def _resolve_gguf_repo(
        self, model
    ) -> tuple[str, list[dict]] | None:
        """Find a GGUF repo for a model, auto-searching if direct repo lacks GGUFs.

        Returns (repo_id, files) or None if user cancels. Shows progress via
        message boxes when searching. Handles the common case where a model's
        original repo (e.g. ``nvidia/Qwen3-30B-A3B-NVFP4``) is not GGUF-format —
        searches for mirror repos (bartowski/, unsloth/, QuantFactory/, etc.).
        """
        from PyQt6.QtWidgets import QInputDialog

        from downloader import list_gguf_files

        # HF org handles are always lowercase, no-space. The catalog's
        # ``model.provider`` may hold a display name like "Mistral AI" —
        # sanitize so the default is at least URL-valid. User can edit.
        def _hf_handle(name: str) -> str:
            return name.strip().replace(" ", "").lower()

        default_repo = (
            f"{_hf_handle(model.provider)}/{model.name}"
            if model.provider
            else model.name
        )

        repo_id, ok = QInputDialog.getText(
            self,
            "HuggingFace repo",
            "Enter the HuggingFace repo ID (org/name), or leave as-is to auto-search:",
            text=default_repo,
        )
        if not ok or "/" not in repo_id:
            return None
        repo_id = repo_id.strip()

        files = list_gguf_files(repo_id, token=self._config.hf_token)
        if files:
            return repo_id, files

        # No GGUFs in direct repo — offer to search for mirrors
        base_name = repo_id.split("/", 1)[1]
        # Strip common quant/format suffixes to improve search hits
        for suffix in ("-NVFP4", "-FP8", "-AWQ", "-GPTQ", "-Instruct"):
            if base_name.upper().endswith(suffix):
                base_name = base_name[: -len(suffix)]
                break

        reply = QMessageBox.question(
            self,
            "No GGUF found",
            f"{repo_id} does not contain any .gguf files (likely a different format).\n\n"
            f"Do you want me to search HuggingFace for '{base_name} GGUF' "
            "mirror repos?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return None

        from hf_api import HuggingFaceAPI

        api = HuggingFaceAPI(token=self._config.hf_token)
        try:
            results = api.search_models(f"{base_name} GGUF", limit=20)
        except Exception as exc:
            QMessageBox.warning(
                self, "Search failed", f"HuggingFace search failed: {exc}"
            )
            return None

        # Filter to repos whose id mentions GGUF — these are the mirrors
        candidates = [
            r for r in results
            if "gguf" in r.get("id", "").lower()
        ]
        if not candidates:
            QMessageBox.warning(
                self,
                "No GGUF mirror found",
                f"No GGUF variant found for '{base_name} GGUF'.\n"
                "Try a repo like 'bartowski/...-GGUF' manually.",
            )
            return None

        picker_dialog = GgufMirrorPickerDialog(base_name, candidates, parent=self)
        if picker_dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        picked = picker_dialog.selected_repo
        if not picked:
            return None

        files = list_gguf_files(picked, token=self._config.hf_token)
        if not files:
            QMessageBox.warning(
                self,
                "Empty repo",
                f"{picked} was listed but no GGUF files could be read from it.",
            )
            return None
        return picked, files

    def _lmstudio_models_dir(self) -> Path:
        """Where LM Studio looks for GGUF files on this OS."""
        # LM Studio uses ~/.lmstudio/models on all platforms by default
        return Path.home() / ".lmstudio" / "models"

    def _on_download_requested(self, fit: ModelFit):
        """User clicked Download in the detail panel."""
        model = fit.model

        # Safety: warn before downloading files from an unverified publisher.
        if not is_trusted_source(model):
            origin = (
                f"\n\nThis appears to be a community re-upload of:\n{model.base_model}"
                if is_reupload(model) else ""
            )
            resp = QMessageBox.warning(
                self,
                "Unverified source",
                f"'{model.provider}' is not a recognised first-party publisher.\n"
                f"You would be downloading and running model files from this source."
                f"{origin}\n\nContinue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return

        # Determine source: offer whichever engines are installed
        from PyQt6.QtWidgets import QInputDialog

        def _state_for(name: str) -> ProviderState:
            for p in self._providers:
                if p.name.lower() == name.lower():
                    return p.state
            return ProviderState.NOT_INSTALLED

        ollama_state = _state_for("ollama")
        lmstudio_state = _state_for("lm studio")

        # Build options labelled so user sees which engine is ready/off
        def _lbl(base: str, state: ProviderState) -> str:
            if state == ProviderState.READY:
                return f"{base}  ✓"
            if state == ProviderState.INSTALLED_OFF:
                return f"{base}  (off — will be started first)"
            return base

        choices: list[tuple[str, str]] = []  # (key, label)
        # READY engines first, then installed-off, then generic fallback
        for key, name, state in (
            ("ollama", "Ollama pull", ollama_state),
            ("lmstudio", "LM Studio (GGUF)", lmstudio_state),
        ):
            if state != ProviderState.NOT_INSTALLED:
                choices.append((key, _lbl(name, state)))
        # Sort: READY (has ✓) first
        choices.sort(key=lambda kv: 0 if "✓" in kv[1] else 1)
        choices.append(("hf", "HuggingFace GGUF (custom folder)"))

        labels = [lbl for _, lbl in choices]
        if len(labels) == 1:
            selected_label = labels[0]
        else:
            selected_label, ok = QInputDialog.getItem(
                self,
                f"Download {model.name}",
                "Choose download source:",
                labels,
                0,
                False,
            )
            if not ok:
                return

        # Map label back to key
        choice_key = next((k for k, lbl in choices if lbl == selected_label), "hf")

        def _offer_fallback(reason: str) -> None:
            """After Ollama fails, offer LM Studio/HF GGUF alternative."""
            alt_choices: list[tuple[str, str]] = []
            if lmstudio_state != ProviderState.NOT_INSTALLED:
                alt_choices.append(("lmstudio", "LM Studio (GGUF)"))
            alt_choices.append(("hf", "HuggingFace GGUF (custom folder)"))

            msg = (
                f"Ollama couldn't download this model:\n\n{reason}\n\n"
                "This model is likely not in the Ollama library. "
                "Do you want to try downloading it as GGUF instead?"
            )
            alt_labels = [lbl for _, lbl in alt_choices]
            selected, ok2 = QInputDialog.getItem(
                self,
                "Alternative source",
                msg,
                alt_labels,
                0,
                False,
            )
            if not ok2:
                return
            key = next((k for k, lbl in alt_choices if lbl == selected), "hf")
            if key == "lmstudio":
                self._start_lmstudio_download(fit)
            else:
                self._start_gguf_download(fit)

        if choice_key == "ollama":
            # Pre-flight: Ollama running?
            if ollama_state != ProviderState.READY:
                reply = QMessageBox.question(
                    self,
                    "Ollama is off",
                    "The Ollama service isn't running right now. "
                    "Do you want to try starting it before downloading?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                from provider_control import start_ollama_service
                if not start_ollama_service():
                    QMessageBox.warning(
                        self,
                        "Failed to start Ollama",
                        "The Ollama service could not be started. Please start "
                        "the Ollama app manually or pick another source.",
                    )
                    return
                self._refresh_providers()
            self._start_ollama_pull(model.name, on_not_found=_offer_fallback)
        elif choice_key == "lmstudio":
            self._start_lmstudio_download(fit)
        else:
            self._start_gguf_download(fit)

    def _start_ollama_pull(self, model_name: str, on_not_found=None):
        from PyQt6.QtWidgets import QInputDialog

        tag, ok = QInputDialog.getText(
            self,
            "Ollama Pull",
            "Enter the Ollama model tag (e.g. 'llama3.1:8b', 'qwen2.5-coder:7b'):",
            text=self._pick_ollama_candidate(model_name) or "",
        )
        if not ok or not tag.strip():
            return

        worker = DownloadWorker(kind=DownloadWorker.KIND_OLLAMA, model_name=tag.strip())
        dialog = DownloadDialog(worker, title=f"Pulling {tag}", parent=self)
        worker.start()
        dialog.exec()
        if dialog.success:
            self._refresh_providers()
            return

        # Detect "model not in Ollama library" errors — offer GGUF fallback
        err = (dialog.message or "").lower()
        not_found_markers = (
            "file does not exist",
            "manifest",
            "not found",
            "no such",
            "pull model manifest",
        )
        if on_not_found and any(m in err for m in not_found_markers):
            on_not_found(dialog.message or "Unknown error")

    def _start_lmstudio_download(self, fit: ModelFit):
        """Download a GGUF directly into LM Studio's models folder.

        LM Studio auto-scans ~/.lmstudio/models/<publisher>/<repo>/*.gguf and
        picks them up without restart. This path mirrors what LM Studio's own
        download UI creates.
        """
        resolved = self._resolve_gguf_repo(fit.model)
        if resolved is None:
            return
        repo_id, files = resolved

        picker = GgufPickerDialog(
            repo_id,
            files,
            parent=self,
            recommended_quant=fit.best_quant,
            vram_budget_gb=fit.memory_available_gb,
        )
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        filename = picker.selected_filename
        if not filename:
            return

        # LM Studio layout: ~/.lmstudio/models/<publisher>/<repo>/<file>.gguf
        publisher, _, repo = repo_id.partition("/")
        dest_dir = self._lmstudio_models_dir() / publisher / repo
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Cannot create directory",
                f"Could not create {dest_dir}:\n{exc}",
            )
            return

        worker = DownloadWorker(
            kind=DownloadWorker.KIND_GGUF,
            repo_id=repo_id,
            filename=filename,
            dest_dir=dest_dir,
            token=self._config.hf_token,
        )
        dialog = DownloadDialog(
            worker,
            title=f"Downloading {filename} → LM Studio",
            parent=self,
        )
        worker.start()
        dialog.exec()

        if dialog.success:
            QMessageBox.information(
                self,
                "Download complete",
                f"Model installed to LM Studio:\n{dest_dir}\n\n"
                "LM Studio should detect it automatically. If not, "
                "click 'Refresh' in LM Studio's My Models tab.",
            )
            self._refresh_providers()

    def _start_gguf_download(self, fit: ModelFit):
        from PyQt6.QtWidgets import QFileDialog

        resolved = self._resolve_gguf_repo(fit.model)
        if resolved is None:
            return
        repo_id, files = resolved

        picker = GgufPickerDialog(
            repo_id,
            files,
            parent=self,
            recommended_quant=fit.best_quant,
            vram_budget_gb=fit.memory_available_gb,
        )
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        filename = picker.selected_filename
        if not filename:
            return

        dest_str = QFileDialog.getExistingDirectory(
            self,
            "Choose download destination",
            str(Path.home() / "Downloads"),
        )
        if not dest_str:
            return

        worker = DownloadWorker(
            kind=DownloadWorker.KIND_GGUF,
            repo_id=repo_id,
            filename=filename,
            dest_dir=Path(dest_str),
            token=self._config.hf_token,
        )
        dialog = DownloadDialog(worker, title=f"Downloading {filename}", parent=self)
        worker.start()
        dialog.exec()

    def _refresh_providers(self):
        """Re-run provider detection (used after a successful install)."""
        if self._provider_worker and self._provider_worker.isRunning():
            return
        self._provider_worker = ProviderWorker()
        self._provider_worker.finished.connect(self._on_providers_detected)
        self._provider_worker.error.connect(lambda e: logger.error("Provider error: %s", e))
        self._provider_worker.start()

    def _on_run_requested(self, fit: ModelFit):
        """User clicked Run — open chat dialog with available providers."""
        from runner import available_providers_for_model

        model = fit.model
        providers = available_providers_for_model(model.name, self._providers)
        if not providers:
            QMessageBox.information(
                self,
                "Not installed",
                f"'{model.name}' doesn't appear to be installed in any running provider.\n"
                "Use the Download button first, or start a provider (Ollama/LM Studio).",
            )
            return

        dialog = ChatDialog(model.name, providers, parent=self)
        dialog.show()
        # Don't exec() — keep it modeless so the user can browse the catalog too

    # -----------------------------------------------------------------------
    # Comparison
    # -----------------------------------------------------------------------

    def _open_comparison(self):
        fits_to_compare = self._table_model.checked_fits()

        if len(fits_to_compare) < 2:
            alert = AlertDialog(
                "Compare Models",
                "Select at least 2 models to compare.\n"
                "Use the checkboxes in the Name column to pick models.",
                self._config.theme,
                self,
            )
            alert.exec()
            return

        dialog = ComparisonDialog(fits_to_compare[:3], self._config.theme, self)
        dialog.exec()

    # -----------------------------------------------------------------------
    # Hardware simulation
    # -----------------------------------------------------------------------

    def _toggle_hwsim(self, checked: bool):
        self._animate_panel_show(self._hwsim_panel, checked, axis="width")
        self._status_bar.set_hw_sim(checked and self._hwsim_panel.is_active)

    def _on_hw_sim_changed(self, sim_specs):
        """Handle hardware simulation change."""
        if sim_specs is None:
            # Reset — use real hardware
            self._status_bar.set_hw_sim(False)
            if self._specs:
                self._system_bar.update_hardware(self._specs)
                self._start_scoring(self._specs)
        else:
            # Apply simulated hardware
            self._status_bar.set_hw_sim(True)
            self._system_bar.update_hardware(sim_specs)
            self._start_scoring(sim_specs)

    # -----------------------------------------------------------------------
    # About
    # -----------------------------------------------------------------------

    def _show_about(self):
        dialog = AboutDialog(theme_name=self._config.theme, parent=self)
        dialog.check_updates_requested.connect(self._check_for_updates_manual)
        dialog.exec()

    def _check_for_updates_manual(self):
        """User-triggered update check with explicit feedback for every outcome."""
        logger.info("Manual update check requested")
        checker = UpdateChecker("thealps01-netizen", "nameweaver")
        # Kept on self so the QThread is not garbage-collected mid-check.
        self._manual_update_checker = checker
        checker.update_available.connect(self._on_update_available)
        checker.no_update.connect(self._on_no_update)
        checker.check_failed.connect(self._on_update_check_failed)
        checker.start()

    def _on_no_update(self):
        AlertDialog(
            "Güncelleme Yok",
            f"En güncel sürümü kullanıyorsunuz (v{__version__}).",
            theme_name=self._config.theme,
            parent=self,
        ).exec()

    def _on_update_check_failed(self):
        AlertDialog(
            "Denetlenemedi",
            "Güncelleme denetlenemedi.\nİnternet bağlantınızı kontrol edip tekrar deneyin.",
            theme_name=self._config.theme,
            parent=self,
        ).exec()

    # -----------------------------------------------------------------------
    # Config persistence
    # -----------------------------------------------------------------------

    def _save_config(self):
        try:
            # splitter removed — no sizes to save
            self._config.filters = self._filter_bar.get_filters()
            save_config(self._config)
        except Exception as exc:
            logger.warning("Failed to save config: %s", exc)

    def _restore_geometry(self):
        c = self._config
        if c.window_x >= 0 and c.window_y >= 0:
            self.move(c.window_x, c.window_y)
        self.resize(c.window_width, c.window_height)

    def closeEvent(self, event):
        """Save state and shut background threads down without freezing the UI."""
        self._config.window_width = self.width()
        self._config.window_height = self.height()
        pos = self.pos()
        self._config.window_x = pos.x()
        self._config.window_y = pos.y()
        self._save_config()

        # Hide immediately so closing feels instant — the user never sees a
        # frozen window while background threads wind down.
        self.hide()

        # Collect every background QThread we own (workers, poller, update checks).
        threads = [
            self._hw_worker,
            self._provider_worker,
            self._scoring_worker,
            self._hf_worker,
            self._provider_start_worker,
            self._provider_stop_worker,
            self._provider_poller,
        ]
        for checker in (
            getattr(self, "_update_checker", None),
            getattr(self, "_manual_update_checker", None),
        ):
            if checker is not None:
                threads.append(getattr(checker, "_thread", None))

        # These workers run blocking work in run() (not a Qt event loop), so
        # quit() is a no-op for them; requestInterruption() lets cooperative
        # loops (e.g. the poller) exit fast. Signal them all FIRST so the waits
        # below overlap instead of serialising (which caused the 1-2 s freeze).
        for t in threads:
            if t and t.isRunning():
                t.requestInterruption()
                t.quit()

        # Give them a brief, bounded chance to finish; force-stop stragglers so
        # we never destroy a running QThread (which would crash on exit).
        for t in threads:
            if t and t.isRunning():
                if not t.wait(500):
                    t.terminate()
                    t.wait(200)

        logger.info("Application closing gracefully")
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    _setup_dpi()
    setup_logging()
    _install_crash_handler()

    if not _acquire_single_instance():
        # Another instance is running
        app = QApplication(sys.argv)
        QMessageBox.information(
            None,
            "Nameweaver",
            "Nameweaver is already running.\nCheck your taskbar.",
        )
        sys.exit(0)

    logger.info("Nameweaver v%s starting", __version__)

    app = QApplication(sys.argv)
    app.setApplicationName("Nameweaver")
    app.setApplicationVersion(__version__)

    # Set App User Model ID for Windows taskbar
    if platform.system() == "Windows":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "nameweaver.Nameweaver"
            )
        except Exception:
            pass

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
