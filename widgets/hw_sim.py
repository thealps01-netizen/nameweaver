"""Hardware simulation panel — override RAM, VRAM, CPU cores."""

import qtawesome as qta
from PyQt6.QtCore import pyqtSignal, QSize, Qt
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from hw import SystemSpecs


class HardwareSimPanel(QWidget):
    """Panel to simulate different hardware configurations."""

    simulation_changed = pyqtSignal(object)  # SystemSpecs or None (reset)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._real_specs: SystemSpecs | None = None
        self._active = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Title
        title = QLabel("Hardware Simulation")
        title.setProperty("class", "section_title")
        layout.addWidget(title)

        # RAM row
        self._ram_spin = self._make_spin_row(
            layout, "mdi6.memory", "RAM",
            QDoubleSpinBox, 1.0, 2048.0, " GB", 1, 4.0,
        )

        # VRAM row
        self._vram_spin = self._make_spin_row(
            layout, "mdi6.expansion-card", "VRAM",
            QDoubleSpinBox, 0.0, 512.0, " GB", 1, 2.0,
        )

        # CPU cores row
        self._cpu_spin = self._make_spin_row(
            layout, "mdi6.cpu-64-bit", "CPU",
            QSpinBox, 1, 256, " cores", 0, 1,
        )

        layout.addSpacing(6)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._apply_btn = QPushButton()
        self._apply_btn.setIcon(qta.icon("mdi6.check-circle-outline", color="#a6e3a1"))
        self._apply_btn.setIconSize(QSize(18, 18))
        self._apply_btn.setText("Apply")
        self._apply_btn.setObjectName("hw_apply_btn")
        self._apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn.setFixedHeight(32)
        self._apply_btn.clicked.connect(self._on_apply)
        btn_layout.addWidget(self._apply_btn)

        self._reset_btn = QPushButton()
        self._reset_btn.setIcon(qta.icon("mdi6.refresh", color="#f38ba8"))
        self._reset_btn.setIconSize(QSize(18, 18))
        self._reset_btn.setText("Reset")
        self._reset_btn.setObjectName("hw_reset_btn")
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_btn.setFixedHeight(32)
        self._reset_btn.clicked.connect(self._on_reset)
        btn_layout.addWidget(self._reset_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

    def _make_spin_row(self, parent_layout, icon_name, label_text,
                       spin_class, min_val, max_val, suffix, decimals, step):
        """Create a labelled spin-box row with an icon and +/- buttons."""
        row = QHBoxLayout()
        row.setSpacing(8)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon(icon_name, color="#89b4fa").pixmap(QSize(20, 20)))
        icon_lbl.setFixedSize(20, 20)
        icon_lbl.setStyleSheet("background: transparent;")
        icon_lbl.setProperty("icon_name", icon_name)
        row.addWidget(icon_lbl)

        lbl = QLabel(label_text)
        lbl.setFixedWidth(40)
        lbl.setStyleSheet("background: transparent; font-size: 12px;")
        row.addWidget(lbl)

        spin = spin_class()
        spin.setButtonSymbols(spin_class.ButtonSymbols.NoButtons)
        if isinstance(spin, QDoubleSpinBox):
            spin.setRange(min_val, max_val)
            spin.setDecimals(decimals)
            spin.setSingleStep(step)
        else:
            spin.setRange(int(min_val), int(max_val))
            spin.setSingleStep(int(step))
        spin.setSuffix(suffix)
        spin.setFixedHeight(28)
        spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(spin, stretch=1)

        # Stash widgets on layout to recolor later
        if not hasattr(self, "_spin_icons"):
            self._spin_icons = []
            self._spin_btns = []
        self._spin_icons.append(icon_lbl)

        # Minus button
        minus_btn = QPushButton()
        minus_btn.setIcon(qta.icon("mdi6.minus", color="#cdd6f4"))
        minus_btn.setIconSize(QSize(14, 14))
        minus_btn.setFixedSize(28, 28)
        minus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        minus_btn.setObjectName("spin_minus_btn")
        minus_btn.clicked.connect(lambda: spin.stepDown())
        row.addWidget(minus_btn)
        self._spin_btns.append((minus_btn, "mdi6.minus"))

        # Plus button
        plus_btn = QPushButton()
        plus_btn.setIcon(qta.icon("mdi6.plus", color="#cdd6f4"))
        plus_btn.setIconSize(QSize(14, 14))
        plus_btn.setFixedSize(28, 28)
        plus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        plus_btn.setObjectName("spin_plus_btn")
        plus_btn.clicked.connect(lambda: spin.stepUp())
        row.addWidget(plus_btn)
        self._spin_btns.append((plus_btn, "mdi6.plus"))

        parent_layout.addLayout(row)
        return spin

    def set_real_specs(self, specs: SystemSpecs):
        """Set the real detected hardware specs."""
        self._real_specs = specs
        self._ram_spin.setValue(specs.total_ram_gb)
        self._vram_spin.setValue(specs.total_gpu_vram_gb)
        self._cpu_spin.setValue(specs.total_cpu_cores)

    @property
    def is_active(self) -> bool:
        return self._active

    def _on_apply(self):
        if self._real_specs is None:
            return

        sim_specs = self._real_specs.with_overrides(
            ram_gb=self._ram_spin.value(),
            vram_gb=self._vram_spin.value(),
            cpu_cores=self._cpu_spin.value(),
        )
        self._active = True
        self.simulation_changed.emit(sim_specs)

    def _on_reset(self):
        if self._real_specs is None:
            return

        self._ram_spin.setValue(self._real_specs.total_ram_gb)
        self._vram_spin.setValue(self._real_specs.total_gpu_vram_gb)
        self._cpu_spin.setValue(self._real_specs.total_cpu_cores)
        self._active = False
        self.simulation_changed.emit(None)

    def set_theme(self, theme_name: str):
        from themes import get_theme
        c = get_theme(theme_name)
        
        self._apply_btn.setIcon(qta.icon("mdi6.check-circle-outline", color="#a6e3a1" if theme_name in ("dark", "dracula", "nord") else c.good))
        self._reset_btn.setIcon(qta.icon("mdi6.refresh", color="#f38ba8" if theme_name in ("dark", "dracula", "nord") else c.error))

        if hasattr(self, "_spin_icons"):
            for icon_lbl in self._spin_icons:
                name = icon_lbl.property("icon_name")
                if name:
                    icon_lbl.setPixmap(qta.icon(name, color=c.accent).pixmap(QSize(20, 20)))
                    
        if hasattr(self, "_spin_btns"):
            for btn, icon_name in self._spin_btns:
                btn.setIcon(qta.icon(icon_name, color=c.fg_muted))
