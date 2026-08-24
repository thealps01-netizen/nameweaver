"""Detail panel — shows selected model info with score bars."""

from PyQt6.QtCore import Qt, QEasingCurve, QPropertyAnimation, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from models import is_engine_compatible, size_class
from scoring import FitLevel, ModelFit, RunMode, pc_comfort, runnability
from themes import ThemeColors, get_theme


class ScoreBar(QWidget):
    """Custom-painted horizontal bar showing a 0-100 score with fill animation."""

    def __init__(self, label: str, value: float = 0, color: str = "#89b4fa", parent=None, label_width: int = 70, show_value: bool = True):
        super().__init__(parent)
        self._label = label
        self._label_width = label_width
        self._show_value = show_value
        self._value = value
        self._display_value = value  # Start at value so it renders immediately if no animation is triggered
        self._color = color
        self._bg_color = "#313244"
        self.setFixedHeight(28)

        self._anim = QPropertyAnimation(self, b"displayValue")
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setDuration(600)

    def _get_display_value(self) -> float:
        return self._display_value

    def _set_display_value(self, val: float):
        self._display_value = val
        self.update()

    displayValue = pyqtProperty(float, _get_display_value, _set_display_value)

    def set_value(self, value: float, color: str | None = None):
        self._value = max(0, min(value, 100))
        if color:
            self._color = color
        # Animate from current display to target
        self._anim.stop()
        self._anim.setStartValue(self._display_value)
        self._anim.setEndValue(self._value)
        self._anim.start()

    def set_bg_color(self, color: str):
        self._bg_color = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        
        # Calculate available width based on visibility settings
        bar_x = self._label_width if self._label else 0
        value_space = 45 if self._show_value else 0
        
        bar_w = w - bar_x - value_space
        if not self._label and not self._show_value:
            bar_w = w

        bar_h = 10
        bar_y = (h - bar_h) // 2

        # Label
        if self._label:
            painter.setPen(QPen(QColor(self._color)))
            painter.drawText(0, 0, bar_x - 8, h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        # Background bar
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._bg_color))
        painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 4, 4)

        # Filled bar (uses animated display value)
        fill_w = int(bar_w * self._display_value / 100)
        if fill_w > 0:
            painter.setBrush(QColor(self._color))
            painter.drawRoundedRect(bar_x, bar_y, fill_w, bar_h, 4, 4)

        if self._show_value:
            # Value text (shows target value, not animated)
            painter.setPen(QPen(QColor(self._color)))
            painter.drawText(
                bar_x + bar_w + 6, 0, 40, h,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{self._value:.0f}",
            )

        painter.end()


class DetailPanel(QWidget):
    """Right panel showing details for the selected model."""

    download_requested = pyqtSignal(object)  # ModelFit
    run_requested = pyqtSignal(object)  # ModelFit

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = get_theme("dark")
        self._current_fit: ModelFit | None = None
        self._setup_ui()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(16, 16, 16, 16)
        self._content_layout.setSpacing(12)

        # Model name
        self._name_label = QLabel("Select a model")
        self._name_label.setProperty("class", "title")
        self._name_label.setWordWrap(True)
        self._content_layout.addWidget(self._name_label)

        # Provider + use case
        self._meta_label = QLabel("")
        self._meta_label.setProperty("class", "muted")
        self._content_layout.addWidget(self._meta_label)

        # Separator
        self._add_separator()

        # Overall score
        self._score_label = QLabel("")
        self._score_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        self._content_layout.addWidget(self._score_label)

        # Score bars
        self._quality_bar = ScoreBar("Quality", 0)
        self._speed_bar = ScoreBar("Speed", 0)
        # "Match" (not "Fit") — this score rewards using your hardware well and
        # is deliberately distinct from the "Fit Level" sizing label below.
        self._fit_bar = ScoreBar("Match", 0)

        for bar in [self._quality_bar, self._speed_bar, self._fit_bar]:
            self._content_layout.addWidget(bar)

        # Separator
        self._add_separator()

        # Details section
        self._details_label = QLabel("")
        self._details_label.setWordWrap(True)
        self._details_label.setTextFormat(Qt.TextFormat.RichText)
        self._content_layout.addWidget(self._details_label)

        # Notes
        self._notes_label = QLabel("")
        self._notes_label.setWordWrap(True)
        self._notes_label.setProperty("class", "muted")
        self._content_layout.addWidget(self._notes_label)

        # Action buttons row
        self._action_row = QHBoxLayout()
        self._action_row.setSpacing(8)

        self._download_btn = QPushButton("Download")
        self._download_btn.setToolTip("Download this model via Ollama or HuggingFace")
        self._download_btn.clicked.connect(self._emit_download)
        self._download_btn.setEnabled(False)
        self._action_row.addWidget(self._download_btn)

        self._run_btn = QPushButton("Run")
        self._run_btn.setToolTip("Chat with this model (must be installed)")
        self._run_btn.clicked.connect(self._emit_run)
        self._run_btn.setEnabled(False)
        self._action_row.addWidget(self._run_btn)

        self._copy_btn = QPushButton("Copy Info")
        self._copy_btn.setToolTip("Copy model summary to clipboard")
        self._copy_btn.clicked.connect(self._copy_info)
        self._copy_btn.setEnabled(False)
        self._action_row.addWidget(self._copy_btn)

        self._action_row.addStretch(1)
        self._content_layout.addLayout(self._action_row)

        self._content_layout.addStretch()

        scroll.setWidget(self._content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _add_separator(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        self._content_layout.addWidget(sep)

    def set_theme(self, theme_name: str):
        self._theme = get_theme(theme_name)
        bg = self._theme.input_bg
        for bar in [self._quality_bar, self._speed_bar, self._fit_bar]:
            bar.set_bg_color(bg)

    def show_model(self, fit: ModelFit | None) -> None:
        """Update panel with selected model data."""
        self._current_fit = fit
        if fit is None:
            self._name_label.setText("Select a model")
            self._meta_label.setText("")
            self._score_label.setText("")
            self._details_label.setText("")
            self._notes_label.setText("")
            for bar in [self._quality_bar, self._speed_bar, self._fit_bar]:
                bar.set_value(0)
            self._download_btn.setEnabled(False)
            self._run_btn.setEnabled(False)
            self._copy_btn.setEnabled(False)
            return

        # Enable action buttons
        self._download_btn.setEnabled(True)
        self._copy_btn.setEnabled(True)
        # Run only if installed AND fits
        can_run = getattr(fit, "installed", False) and fit.fit_level != FitLevel.TOO_TIGHT
        self._run_btn.setEnabled(can_run)
        self._run_btn.setToolTip(
            "Chat with this model" if can_run
            else "Install the model first via Download"
        )

        c = self._theme
        model = fit.model
        sc = fit.score_components

        # Name
        self._name_label.setText(model.name)

        # Meta
        caps = ", ".join(model.capabilities) if model.capabilities else ""
        caps_text = f" | {caps}" if caps else ""
        self._meta_label.setText(
            f"{model.provider} | {model.use_case.capitalize()}{caps_text}"
        )

        # Score with color
        score_color = c.score_high if fit.score >= 75 else c.score_mid if fit.score >= 50 else c.score_low
        self._score_label.setText(f'<span style="color:{score_color};">{fit.score:.1f}</span> / 100')

        # Score bars
        def bar_color(val):
            if val >= 75:
                return c.score_high
            elif val >= 50:
                return c.score_mid
            return c.score_low

        # Reset bars to 0 instantly, then animate to target (loading effect)
        for bar in [self._quality_bar, self._speed_bar, self._fit_bar]:
            bar._anim.stop()
            bar._display_value = 0.0
            bar.update()

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(30, lambda: self._animate_bars(sc, bar_color))

        # Fit level color
        fit_colors = {
            FitLevel.PERFECT: c.fit_perfect,
            FitLevel.GOOD: c.fit_good,
            FitLevel.MARGINAL: c.fit_marginal,
            FitLevel.TOO_TIGHT: c.fit_tight,
        }
        fit_color = fit_colors.get(fit.fit_level, c.fg)

        # Run mode color
        mode_colors = {
            RunMode.GPU: c.mode_gpu,
            RunMode.MOE_OFFLOAD: c.mode_moe,
            RunMode.CPU_OFFLOAD: c.mode_offload,
            RunMode.CPU_ONLY: c.mode_cpu,
        }
        mode_color = mode_colors.get(fit.run_mode, c.fg)

        # Details
        params = model.params_b()
        params_text = f"{params:.1f}B" if params >= 1 else f"{params * 1000:.0f}M"
        disk_gb = model.estimate_disk_gb(fit.best_quant)

        # Size class + PC comfort (small-vs-large + how hard this PC works)
        size_label, size_key = size_class(params)
        size_color = {
            "tiny": c.good, "small": c.good, "medium": c.fg,
            "large": c.warning, "xl": c.error, "huge": c.error,
        }.get(size_key, c.fg_muted)
        comfort_label, comfort_key = pc_comfort(fit)
        comfort_color = {
            "effortless": c.good, "comfortable": c.good,
            "demanding": c.warning, "heavy": c.warning, "too_much": c.error,
        }.get(comfort_key, c.fg)

        ctx = model.ctx_length
        if ctx >= 1_000_000:
            ctx_text = f"{ctx / 1_000_000:.0f}M tokens"
        elif ctx >= 1000:
            ctx_text = f"{ctx // 1000}K tokens"
        else:
            ctx_text = f"{ctx} tokens"

        moe_text = ""
        if model.is_moe():
            moe_text = (
                f'<br><b>Architecture:</b> MoE ({model.expert_count} experts, '
                f'{model.active_experts} active)'
            )

        # Runnability (traffic light) + which engine(s) have it installed.
        runs_label, runs_key = runnability(fit)
        runs_color = {"green": c.good, "yellow": c.warning,
                      "red": c.error}.get(runs_key, c.fg)
        runs_note = ""
        if not is_engine_compatible(model.format):
            runs_note = (
                f'<span style="color:{c.fg_muted};"> — {model.format.upper()} '
                "won't run on your local engines (they run GGUF)</span>"
            )
        installed_in = getattr(fit, "installed_providers", []) or []
        if installed_in:
            installed_html = (
                f'<span style="color:{c.good};">{", ".join(installed_in)}</span>'
            )
        else:
            installed_html = f'<span style="color:{c.fg_muted};">Not installed</span>'

        details_html = f"""
        <table style="border-spacing: 4px;">
        <tr><td style="color:{c.fg_muted};">Runs:</td>
            <td><span style="color:{runs_color}; font-weight:600;">{runs_label}</span>{runs_note}</td></tr>
        <tr><td style="color:{c.fg_muted};">Installed:</td><td>{installed_html}</td></tr>
        <tr><td style="color:{c.fg_muted};">Parameters:</td>
            <td>{params_text} <span style="color:{size_color};">· {size_label}</span></td></tr>
        <tr><td style="color:{c.fg_muted};">PC Load:</td>
            <td><span style="color:{comfort_color};">{comfort_label}</span></td></tr>
        <tr><td style="color:{c.fg_muted};">Quantization:</td><td>{fit.best_quant}</td></tr>
        <tr><td style="color:{c.fg_muted};">Disk Size:</td><td>{disk_gb:.1f} GB</td></tr>
        <tr><td style="color:{c.fg_muted};">Context:</td><td>{ctx_text}</td></tr>
        <tr><td style="color:{c.fg_muted};">Memory:</td>
            <td>{fit.memory_required_gb:.1f} / {fit.memory_available_gb:.1f} GB ({fit.utilization_pct:.0f}%)</td></tr>
        <tr><td style="color:{c.fg_muted};">Run Mode:</td>
            <td><span style="color:{mode_color};">{fit.run_mode.value}</span></td></tr>
        <tr><td style="color:{c.fg_muted};">Fit Level:</td>
            <td><span style="color:{fit_color};">{fit.fit_level.value}</span>
            <span style="color:{c.fg_muted};"> — {fit.fit_level.short_hint}</span></td></tr>
        <tr><td style="color:{c.fg_muted};">Est. TPS:</td><td>{fit.estimated_tps:.1f} tok/s</td></tr>
        <tr><td style="color:{c.fg_muted};">License:</td><td>{model.license or 'Unknown'}</td></tr>
        <tr><td style="color:{c.fg_muted};">Released:</td><td>{model.release_date or 'Unknown'}</td></tr>
        </table>
        {moe_text}
        """
        self._details_label.setText(details_html)

        # Notes
        if fit.notes:
            self._notes_label.setText("\n".join(f"- {n}" for n in fit.notes))
        else:
            self._notes_label.setText("")

    def _animate_bars(self, sc, bar_color):
        """Animate score bars from 0 to their target values."""
        self._quality_bar.set_value(sc.quality, bar_color(sc.quality))
        self._speed_bar.set_value(sc.speed, bar_color(sc.speed))
        self._fit_bar.set_value(sc.fit, bar_color(sc.fit))

    # -----------------------------------------------------------------------
    # Action handlers
    # -----------------------------------------------------------------------

    def _emit_download(self):
        if self._current_fit is not None:
            self.download_requested.emit(self._current_fit)

    def _emit_run(self):
        if self._current_fit is not None:
            self.run_requested.emit(self._current_fit)

    def _copy_info(self):
        if self._current_fit is None:
            return
        fit = self._current_fit
        m = fit.model
        sc = fit.score_components
        text = (
            f"{m.name} ({m.provider})\n"
            f"  Parameters: {m.parameter_count}\n"
            f"  Use case: {m.use_case}\n"
            f"  Quantization: {fit.best_quant}\n"
            f"  Context: {m.ctx_length} tokens\n"
            f"  Memory: {fit.memory_required_gb:.1f} / {fit.memory_available_gb:.1f} GB "
            f"({fit.utilization_pct:.0f}%)\n"
            f"  Run mode: {fit.run_mode.value}\n"
            f"  Fit level: {fit.fit_level.value}\n"
            f"  Estimated TPS: {fit.estimated_tps:.1f} tok/s\n"
            f"  Score: {fit.score:.1f}/100 "
            f"(Q={sc.quality:.0f} S={sc.speed:.0f} M={sc.fit:.0f})\n"
            f"  License: {m.license or 'Unknown'}\n"
        )
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
