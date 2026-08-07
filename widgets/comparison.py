"""Side-by-side model comparison widget."""

import qtawesome as qta
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from scoring import FitLevel, ModelFit, RunMode
from themes import ThemeColors, get_theme
from widgets.detail_panel import ScoreBar


class ComparisonDialog(QDialog):
    """Dialog for comparing 2-3 models side by side."""

    def __init__(self, fits: list[ModelFit], theme_name: str = "dark", parent=None):
        super().__init__(parent)
        self._fits = fits[:3]  # Max 3
        self._theme = get_theme(theme_name)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(1000, 650)
        self.resize(1100, 750)
        self._drag_pos = None
        self._setup_ui()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.pos().y() < 50:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def _setup_ui(self):
        c = self._theme

        # ── Outer wrapper for shadow margin ───────────────────
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

        container = QFrame()
        container.setObjectName("dialog_container")
        container.setStyleSheet(
            f"QFrame#dialog_container {{ background: {c.bg}; border: 1px solid {c.accent};"
            f" border-radius: 12px; }}"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 2)
        _sc = QColor(c.accent)
        _sc.setAlpha(60)
        shadow.setColor(_sc)
        container.setGraphicsEffect(shadow)

        layout = QVBoxLayout(container)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 12)
        outer.addWidget(container)

        # ── Header ────────────────────────────────────────────
        _ah = c.accent.lstrip("#")
        _ar, _ag, _ab = int(_ah[0:2], 16), int(_ah[2:4], 16), int(_ah[4:6], 16)
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 rgba({_ar},{_ag},{_ab},0.25), stop:1 {c.bg_alt});"
            f" border-bottom: 1px solid {c.border};"
            f" border-top-left-radius: 11px; border-top-right-radius: 11px; }}"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 14, 20, 14)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(
            qta.icon("mdi6.scale-balance", color=c.accent).pixmap(QSize(36, 36))
        )
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        header_layout.addWidget(icon_lbl)

        title = QLabel("Model Comparison")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {c.fg}; background: transparent; border: none;"
        )
        header_layout.addWidget(title)
        header_layout.addStretch()

        close_btn = QPushButton()
        close_btn.setIcon(qta.icon("mdi6.close", color=c.fg_muted))
        close_btn.setIconSize(QSize(28, 28))
        close_btn.setFixedSize(36, 36)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: rgba(255,80,80,0.25); }}"
        )
        close_btn.clicked.connect(self.close)
        header_layout.addWidget(close_btn)
        layout.addWidget(header)

        # ── Body ──────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setObjectName("comparison_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea#comparison_scroll, QScrollArea#comparison_scroll > QWidget, QScrollArea#comparison_scroll > QWidget > QWidget {{ background: transparent; border: none; }}"
        )

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 16, 20, 16)
        body_layout.setSpacing(16)

        n = len(self._fits)

        # ── Model name cards ─────────────────────────────────
        names_row = QHBoxLayout()
        names_row.setSpacing(12)
        # Empty space for row labels
        spacer = QLabel()
        spacer.setFixedWidth(160)
        spacer.setStyleSheet("background: transparent;")
        names_row.addWidget(spacer)
        
        names_row.addWidget(self._v_sep())

        for i, fit in enumerate(self._fits):
            if i > 0:
                names_row.addWidget(self._v_sep())

            # Card wrapper to apply alignment correctly
            card_wrapper = QFrame()
            card_wrapper.setStyleSheet("background: transparent;")
            c_layout = QVBoxLayout(card_wrapper)
            c_layout.setContentsMargins(10, 0, 10, 0)
            
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background: {c.bg_alt}; border: 1px solid {c.border}; border-radius: 12px; }}"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(4)
            card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            name_lbl = QLabel(fit.model.name)
            name_lbl.setStyleSheet(
                f"font-weight: 700; font-size: 13px; color: {c.accent}; background: transparent; border: none;"
            )
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setWordWrap(True)
            card_layout.addWidget(name_lbl)

            prov_lbl = QLabel(fit.model.provider)
            prov_lbl.setStyleSheet(
                f"font-size: 11px; color: {c.fg_muted}; background: transparent; border: none;"
            )
            prov_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(prov_lbl)

            c_layout.addWidget(card)
            names_row.addWidget(card_wrapper, stretch=1)
        body_layout.addLayout(names_row)

        # ── Score section ─────────────────────────────────────
        body_layout.addWidget(self._section_label("mdi6.star-outline", "Scores"))
        score_fields = [
            ("Overall", [f.score for f in self._fits]),
            ("Quality", [f.score_components.quality for f in self._fits]),
            ("Speed", [f.score_components.speed for f in self._fits]),
            ("Fit", [f.score_components.fit for f in self._fits]),
        ]
        for i, (label, vals) in enumerate(score_fields):
            if i > 0:
                body_layout.addWidget(self._h_sep())
            body_layout.addLayout(self._bar_row(label, vals, max_val=100))

        # ── Performance section ───────────────────────────────
        body_layout.addWidget(self._section_label("mdi6.speedometer", "Performance"))
        perf_rows = [
            ("TPS", [f"{f.estimated_tps:.1f}" for f in self._fits]),
            ("Memory", [f"{f.memory_required_gb:.1f} / {f.memory_available_gb:.1f} GB" for f in self._fits]),
            ("Utilization", [f"{f.utilization_pct:.0f}%" for f in self._fits]),
            ("Disk", [f"{f.model.estimate_disk_gb(f.best_quant):.1f} GB" for f in self._fits]),
        ]
        for i, (label, vals) in enumerate(perf_rows):
            if i > 0:
                body_layout.addWidget(self._h_sep())
            body_layout.addLayout(self._text_row(label, vals))

        # ── Details section ───────────────────────────────────
        body_layout.addWidget(self._section_label("mdi6.information-outline", "Details"))
        detail_rows = [
            ("Parameters", [self._fmt_params(f) for f in self._fits]),
            ("Quantization", [f.best_quant for f in self._fits]),
            ("Run Mode", [f.run_mode.value for f in self._fits]),
            ("Fit Level", [f.fit_level.value for f in self._fits]),
            ("Context Length", [self._fmt_ctx(f) for f in self._fits]),
            ("Use Case", [f.model.use_case.capitalize() for f in self._fits]),
            ("License", [f.model.license or "Unknown" for f in self._fits]),
        ]
        for i, (label, vals) in enumerate(detail_rows):
            if i > 0:
                body_layout.addWidget(self._h_sep())
            body_layout.addLayout(self._text_row(label, vals, colorize=label in ("Fit Level", "Run Mode")))

        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, stretch=1)

    # ── Helpers ───────────────────────────────────────────────

    def _v_sep(self) -> QFrame:
        sep = QFrame()
        sep.setFixedWidth(1)
        # Margin fix to be same height
        sep.setStyleSheet(f"background: {self._theme.border}; border: none; margin-top: 4px; margin-bottom: 4px;")
        return sep

    def _h_sep(self) -> QFrame:
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {self._theme.border}; border: none; margin-left: 172px;")
        return sep

    def _section_label(self, icon_name: str, text: str) -> QWidget:
        c = self._theme
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 8, 0, 2)
        row_layout.setSpacing(6)

        icon = QLabel()
        icon.setPixmap(qta.icon(icon_name, color=c.accent).pixmap(QSize(28, 28)))
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("background: transparent;")
        row_layout.addWidget(icon)

        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {c.fg_muted}; letter-spacing: 1px; background: transparent;"
        )
        row_layout.addWidget(lbl)
        row_layout.addStretch()
        return row

    def _bar_row(self, label: str, values: list[float], max_val: float = 100) -> QHBoxLayout:
        c = self._theme
        row = QHBoxLayout()
        row.setSpacing(12)

        lbl = QLabel(label)
        lbl.setFixedWidth(160)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet(f"color: {c.fg_muted}; font-size: 12px; font-weight: 600;")
        row.addWidget(lbl)
        
        row.addWidget(self._v_sep())

        best = max(values)
        for i, val in enumerate(values):
            if i > 0:
                row.addWidget(self._v_sep())

            cell = QFrame()
            cell.setStyleSheet(f"background: transparent;")
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(10, 0, 10, 0)
            cell_layout.setSpacing(10)

            bar = ScoreBar(label="", value=val, color=c.accent if val == best and len(values) > 1 else c.fg_muted, show_value=False)
            # Create a loading effect by rendering from 0
            bar._display_value = 0.0
            bar.set_bg_color(c.selection_bg)
            bar.setMinimumWidth(30)
            bar.setFixedHeight(22)
            cell_layout.addWidget(bar, stretch=1)
            
            # Animate the bar slightly later so it feels cohesive
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(150 + (i * 50), lambda b=bar, v=val: b.set_value(v))

            val_lbl = QLabel(f"{val:.1f}")
            val_lbl.setFixedWidth(36)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            style = f"font-size: 13px; font-weight: 700; color: {c.good};" if val == best and len(values) > 1 else f"font-size: 13px; font-weight: 600; color: {c.fg};"
            val_lbl.setStyleSheet(style)
            cell_layout.addWidget(val_lbl)

            row.addWidget(cell, stretch=1)

        return row

    def _text_row(self, label: str, values: list[str], colorize: bool = False) -> QHBoxLayout:
        c = self._theme
        row = QHBoxLayout()
        row.setSpacing(12)

        lbl = QLabel(label)
        lbl.setFixedWidth(160)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet(f"color: {c.fg_muted}; font-size: 12px; font-weight: 600;")
        row.addWidget(lbl)
        
        row.addWidget(self._v_sep())

        for i, val in enumerate(values):
            if i > 0:
                row.addWidget(self._v_sep())

            val_lbl = QLabel(val)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            style = f"font-size: 12px; color: {c.fg};"

            if colorize and label == "Fit Level":
                fit_colors = {
                    "Perfect": c.fit_perfect, "Good": c.fit_good,
                    "Marginal": c.fit_marginal, "Too Tight": c.fit_tight,
                }
                color = fit_colors.get(val, c.fg)
                style = f"font-size: 12px; font-weight: 700; color: {color};"
            elif colorize and label == "Run Mode":
                mode_colors = {
                    "GPU": c.mode_gpu, "MoE Offload": c.mode_moe,
                    "CPU Offload": c.mode_offload, "CPU Only": c.mode_cpu,
                }
                color = mode_colors.get(val, c.fg)
                style = f"font-size: 12px; color: {color};"

            val_lbl.setStyleSheet(style)
            
            cell = QFrame()
            cell.setStyleSheet("background: transparent;")
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(10, 0, 10, 0)
            cell_layout.addWidget(val_lbl, stretch=1)
            
            row.addWidget(cell, stretch=1)

        return row

    def _fmt_params(self, fit: ModelFit) -> str:
        p = fit.model.params_b()
        return f"{p:.1f}B" if p >= 1 else f"{p * 1000:.0f}M"

    def _fmt_ctx(self, fit: ModelFit) -> str:
        ctx = fit.model.ctx_length
        if ctx >= 1_000_000:
            return f"{ctx / 1_000_000:.0f}M"
        elif ctx >= 1000:
            return f"{ctx // 1000}K"
        return str(ctx)
