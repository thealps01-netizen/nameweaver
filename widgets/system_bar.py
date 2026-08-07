"""System info bar — card-style hardware and provider summary with icons.

The GPU card is clickable; tapping it opens a popup listing every detected
GPU with a checkbox so the user can include/exclude cards from the fit
calculation. Emits ``gpu_selection_changed`` with the list of active GPU
names whenever a checkbox toggles.
"""

import qtawesome as qta
from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from hw import SystemSpecs, has_mixed_backends
from providers import ProviderStatus
from themes import ThemeColors, get_theme


class _SysCard(QFrame):
    """Single info chip: icon + label + value + optional dropdown chevron."""

    clicked = pyqtSignal()

    def __init__(
        self,
        icon_name: str,
        label: str,
        theme: ThemeColors,
        parent=None,
        clickable: bool = False,
    ):
        super().__init__(parent)
        self.setObjectName("sys_card")
        self._icon_name = icon_name
        self._theme = theme
        self._clickable = clickable

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        self._icon_lbl = QLabel()
        self._icon_lbl.setPixmap(
            qta.icon(icon_name, color=theme.accent).pixmap(QSize(24, 24))
        )
        self._icon_lbl.setFixedSize(28, 28)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self._icon_lbl)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self._label = QLabel(label.upper())
        self._label.setStyleSheet(
            f"font-size: 10px; font-weight: 700; color: {theme.fg_muted};"
            " letter-spacing: 1px; background: transparent; border: none;"
        )
        text_col.addWidget(self._label)

        self._value = QLabel("…")
        self._value.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {theme.fg};"
            " background: transparent; border: none;"
        )
        text_col.addWidget(self._value)

        layout.addLayout(text_col)

        # Optional chevron for clickable cards
        self._chevron = None
        if clickable:
            layout.addStretch(1)
            self._chevron = QLabel()
            self._chevron.setPixmap(
                qta.icon("mdi6.chevron-down", color=theme.fg_muted).pixmap(QSize(18, 18))
            )
            self._chevron.setStyleSheet("background: transparent; border: none;")
            layout.addWidget(self._chevron)
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_value(self, text: str):
        self._value.setText(text)

    def set_value_html(self, html: str):
        self._value.setText(html)

    def refresh_theme(self, theme: ThemeColors):
        self._theme = theme
        self._icon_lbl.setPixmap(
            qta.icon(self._icon_name, color=theme.accent).pixmap(QSize(24, 24))
        )
        self._label.setStyleSheet(
            f"font-size: 10px; font-weight: 700; color: {theme.fg_muted};"
            " letter-spacing: 1px; background: transparent; border: none;"
        )
        self._value.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {theme.fg};"
            " background: transparent; border: none;"
        )
        if self._chevron is not None:
            self._chevron.setPixmap(
                qta.icon("mdi6.chevron-down", color=theme.fg_muted).pixmap(QSize(18, 18))
            )


class SystemBar(QWidget):
    """Card-style system info strip: CPU | RAM | GPU.

    The GPU card is clickable and opens a popup listing every detected GPU
    with a toggle; ``gpu_selection_changed`` emits the names of the
    currently-enabled GPUs whenever a checkbox changes.
    """

    gpu_selection_changed = pyqtSignal(list)  # list[str] of enabled GPU names

    def __init__(self, theme_name: str = "dark", parent=None):
        super().__init__(parent)
        self._theme_name = theme_name
        self._specs: SystemSpecs | None = None
        t = get_theme(theme_name)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._cpu_card = _SysCard("mdi6.cpu-64-bit", "CPU", t)
        self._ram_card = _SysCard("mdi6.memory", "RAM", t)
        self._gpu_card = _SysCard("mdi6.expansion-card", "GPU", t, clickable=True)
        self._gpu_card.clicked.connect(self._show_gpu_popup)

        for card in (self._cpu_card, self._ram_card, self._gpu_card):
            card.setStyleSheet(
                f"QFrame#sys_card {{ background: {t.bg_alt}; border: 1px solid {t.border};"
                f" border-radius: 12px; }}"
                f" QFrame#sys_card:hover {{ border-color: {t.accent}; }}"
            )
            layout.addWidget(card, stretch=1)

    def update_hardware(self, specs: SystemSpecs) -> None:
        self._specs = specs
        cpu = specs.cpu_name

        # Clean up common CPU suffixes that waste space
        cpu = (
            cpu.replace(" Processor", "")
            .replace(" 12-Core", "")
            .replace(" 16-Core", "")
            .replace(" 8-Core", "")
            .strip()
        )
        if len(cpu) > 28:
            cpu = cpu[:25] + "…"

        self._cpu_card.set_value(f"{cpu}  |  {specs.total_cpu_cores} Cores")
        self._ram_card.set_value(
            f"{specs.total_ram_gb:.1f} GB Total  |  {specs.available_ram_gb:.1f} GB Free"
        )

        if specs.has_gpu and specs.gpus:
            enabled_gpus = [g for g in specs.gpus if g.enabled]
            total_enabled_vram = sum(g.vram_gb for g in enabled_gpus)
            n = len(specs.gpus)
            if n > 1:
                primary = enabled_gpus[0] if enabled_gpus else specs.gpus[0]
                pname = primary.name.replace(" Graphics", "").strip()
                if len(pname) > 20:
                    pname = pname[:17] + "…"
                extra = len([g for g in specs.gpus if g is not primary])
                self._gpu_card.set_value(
                    f"{pname} + {extra} more  |  {total_enabled_vram:.1f} GB VRAM"
                )
            else:
                gpu = specs.gpus[0].name.replace(" Graphics", "").strip()
                if len(gpu) > 28:
                    gpu = gpu[:25] + "…"
                self._gpu_card.set_value(
                    f"{gpu}  |  {specs.total_gpu_vram_gb:.1f} GB VRAM"
                )
        elif specs.has_gpu:
            gpu = specs.gpu_name.replace(" Graphics", "").strip()
            if len(gpu) > 28:
                gpu = gpu[:25] + "…"
            self._gpu_card.set_value(f"{gpu}  |  {specs.total_gpu_vram_gb:.1f} GB VRAM")
        else:
            self._gpu_card.set_value("No GPU Detected")

    def _show_gpu_popup(self) -> None:
        """Open the GPU-selection popup anchored below the GPU card."""
        if self._specs is None or not self._specs.gpus:
            return

        t = get_theme(self._theme_name)
        menu = QMenu(self)
        menu.setObjectName("gpu_popup")

        # Optional header: mixed-backend warning
        if has_mixed_backends(self._specs):
            header = QLabel(
                "  ⚠  Mixed GPU backends — parallel inference may be limited"
            )
            header.setStyleSheet(
                f"color: {t.warning}; font-size: 11px; font-weight: 600;"
                f" padding: 6px 12px; background: transparent; border: none;"
            )
            hdr_act = QWidgetAction(menu)
            hdr_act.setDefaultWidget(header)
            menu.addAction(hdr_act)
            menu.addSeparator()

        # One checkbox row per GPU
        for gpu in self._specs.gpus:
            tag = "iGPU" if gpu.integrated else gpu.backend.value.upper()
            label_txt = f"  {gpu.name}  —  {gpu.vram_gb:.1f} GB · {tag}"
            cb = QCheckBox(label_txt)
            cb.setChecked(gpu.enabled)
            cb.setStyleSheet(
                f"QCheckBox {{ color: {t.fg}; font-size: 12px; padding: 6px 12px; }}"
                f"QCheckBox::indicator {{ width: 16px; height: 16px; }}"
            )
            # Capture current gpu via default arg
            cb.toggled.connect(
                lambda checked, g=gpu: self._on_gpu_toggled(g, checked)
            )
            row_act = QWidgetAction(menu)
            row_act.setDefaultWidget(cb)
            menu.addAction(row_act)

        # Anchor below the GPU card
        anchor = self._gpu_card.mapToGlobal(QPoint(0, self._gpu_card.height()))
        menu.exec(anchor)

    def _on_gpu_toggled(self, gpu, checked: bool) -> None:
        gpu.enabled = bool(checked)
        if self._specs is not None:
            active = [g.name for g in self._specs.gpus if g.enabled]
            # Refresh total VRAM on specs so downstream consumers see it
            self._specs.total_gpu_vram_gb = sum(
                g.vram_gb for g in self._specs.gpus if g.enabled
            )
            self.update_hardware(self._specs)
            self.gpu_selection_changed.emit(active)

    def update_providers(self, providers: list[ProviderStatus], theme_name: str = "dark") -> None:
        pass  # Providers card removed

    def refresh_theme(self, theme_name: str) -> None:
        self._theme_name = theme_name
        t = get_theme(theme_name)
        for card in (self._cpu_card, self._ram_card, self._gpu_card):
            card.setStyleSheet(
                f"QFrame#sys_card {{ background: {t.bg_alt}; border: 1px solid {t.border};"
                f" border-radius: 12px; }}"
                f" QFrame#sys_card:hover {{ border-color: {t.accent}; }}"
            )
            card.refresh_theme(t)
