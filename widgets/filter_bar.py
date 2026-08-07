"""Search and filter bar with dropdown filters."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QWidget,
)

from models import UseCase
from scoring import FitLevel


class FilterBar(QWidget):
    """Horizontal bar with search input and filter dropdowns.

    Row 1: search, provider, use-case, fit level
    Row 2: quantization, license, capability, installed-only toggle
    """

    filters_changed = pyqtSignal()
    # Emitted when the quality/speed bias slider moves. Value ∈ [0.0, 1.0]
    # where 0.0 = pure speed, 0.5 = neutral, 1.0 = pure quality.
    preference_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search models...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_filter_changed)
        outer.addWidget(self._search, stretch=2)

        # Provider
        self._provider_combo = QComboBox()
        self._provider_combo.addItem("Provider", "")
        self._provider_combo.currentIndexChanged.connect(self._on_filter_changed)
        outer.addWidget(self._provider_combo, stretch=1)

        # Use Case
        self._usecase_combo = QComboBox()
        self._usecase_combo.addItem("Use Case", "")
        for uc in UseCase:
            self._usecase_combo.addItem(uc.value.capitalize(), uc.value)
        self._usecase_combo.currentIndexChanged.connect(self._on_filter_changed)
        outer.addWidget(self._usecase_combo, stretch=1)

        # Fit
        self._fit_combo = QComboBox()
        self._fit_combo.addItem("Fit", "")
        for fl in FitLevel:
            self._fit_combo.addItem(fl.value, fl.value)
        self._fit_combo.currentIndexChanged.connect(self._on_filter_changed)
        outer.addWidget(self._fit_combo, stretch=1)

        # Quant
        self._quant_combo = QComboBox()
        self._quant_combo.addItem("Quant", "")
        self._quant_combo.currentIndexChanged.connect(self._on_filter_changed)
        outer.addWidget(self._quant_combo, stretch=1)

        # License
        self._license_combo = QComboBox()
        self._license_combo.addItem("License", "")
        self._license_combo.currentIndexChanged.connect(self._on_filter_changed)
        outer.addWidget(self._license_combo, stretch=1)

        # Capability
        self._cap_combo = QComboBox()
        self._cap_combo.addItem("Capability", "")
        self._cap_combo.addItem("Vision", "vision")
        self._cap_combo.addItem("Tool Use", "tool_use")
        self._cap_combo.currentIndexChanged.connect(self._on_filter_changed)
        outer.addWidget(self._cap_combo, stretch=1)

        # Min TPS — hides models whose estimated throughput is below target
        self._min_tps_combo = QComboBox()
        self._min_tps_combo.addItem("Min TPS", "0")
        for tps in ("5", "10", "20", "30", "50"):
            self._min_tps_combo.addItem(f"≥ {tps} tok/s", tps)
        self._min_tps_combo.setToolTip(
            "Target tokens per second — models below this are hidden"
        )
        self._min_tps_combo.currentIndexChanged.connect(self._on_filter_changed)
        outer.addWidget(self._min_tps_combo, stretch=1)

        # Installed only
        self._installed_checkbox = QCheckBox("Installed")
        self._installed_checkbox.stateChanged.connect(self._on_filter_changed)
        outer.addWidget(self._installed_checkbox)

        # Quality ↔ Speed preference slider — biases the composite score
        # without re-analyzing models (uses stored score_components).
        self._speed_lbl = QLabel("Speed")
        self._speed_lbl.setStyleSheet("font-size: 11px; padding: 0 4px;")
        outer.addWidget(self._speed_lbl)

        self._pref_slider = QSlider(Qt.Orientation.Horizontal)
        self._pref_slider.setRange(0, 100)
        self._pref_slider.setValue(50)
        self._pref_slider.setFixedWidth(80)
        self._pref_slider.setToolTip(
            "Left: prefer faster models · Right: prefer higher-quality models"
        )
        self._pref_slider.valueChanged.connect(self._on_preference_changed)
        outer.addWidget(self._pref_slider)

        self._quality_lbl = QLabel("Quality")
        self._quality_lbl.setStyleSheet("font-size: 11px; padding: 0 4px;")
        outer.addWidget(self._quality_lbl)

    def populate_providers(self, providers: list[str]) -> None:
        """Populate the provider dropdown with discovered providers."""
        current = self._provider_combo.currentData()
        self._provider_combo.blockSignals(True)
        self._provider_combo.clear()
        self._provider_combo.addItem("All", "")
        for p in sorted(set(providers)):
            self._provider_combo.addItem(p, p)
        idx = self._provider_combo.findData(current)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        self._provider_combo.blockSignals(False)

    def populate_quants(self, quants: list[str]) -> None:
        """Populate quantization dropdown from loaded model catalog."""
        current = self._quant_combo.currentData()
        self._quant_combo.blockSignals(True)
        self._quant_combo.clear()
        self._quant_combo.addItem("All", "")
        for q in sorted(set(quants)):
            if q:
                self._quant_combo.addItem(q, q)
        idx = self._quant_combo.findData(current)
        if idx >= 0:
            self._quant_combo.setCurrentIndex(idx)
        self._quant_combo.blockSignals(False)

    def populate_licenses(self, licenses: list[str]) -> None:
        """Populate license dropdown from loaded model catalog."""
        current = self._license_combo.currentData()
        self._license_combo.blockSignals(True)
        self._license_combo.clear()
        self._license_combo.addItem("All", "")
        for lic in sorted(set(licenses)):
            if lic:
                self._license_combo.addItem(lic, lic)
        idx = self._license_combo.findData(current)
        if idx >= 0:
            self._license_combo.setCurrentIndex(idx)
        self._license_combo.blockSignals(False)

    def _on_filter_changed(self):
        self.filters_changed.emit()

    def _on_preference_changed(self, value: int) -> None:
        self.preference_changed.emit(value / 100.0)

    @property
    def score_preference(self) -> float:
        """Current slider value ∈ [0.0, 1.0]."""
        return self._pref_slider.value() / 100.0

    def set_score_preference(self, value: float) -> None:
        """Programmatically set slider without emitting the signal."""
        clamped = max(0.0, min(1.0, float(value)))
        self._pref_slider.blockSignals(True)
        self._pref_slider.setValue(int(round(clamped * 100)))
        self._pref_slider.blockSignals(False)

    def reset_filters(self):
        """Reset all filters to default values."""
        self._search.clear()
        for combo in (self._provider_combo, self._usecase_combo, self._fit_combo,
                      self._quant_combo, self._license_combo, self._cap_combo,
                      self._min_tps_combo):
            combo.setCurrentIndex(0)
        self._installed_checkbox.setChecked(False)

    @property
    def search_text(self) -> str:
        return self._search.text().strip().lower()

    @property
    def provider_filter(self) -> str:
        return self._provider_combo.currentData() or ""

    @property
    def usecase_filter(self) -> str:
        return self._usecase_combo.currentData() or ""

    @property
    def fit_filter(self) -> str:
        return self._fit_combo.currentData() or ""

    @property
    def quant_filter(self) -> str:
        return self._quant_combo.currentData() or ""

    @property
    def license_filter(self) -> str:
        return self._license_combo.currentData() or ""

    @property
    def capability_filter(self) -> str:
        return self._cap_combo.currentData() or ""

    @property
    def installed_only(self) -> bool:
        return self._installed_checkbox.isChecked()

    @property
    def min_tps(self) -> float:
        """Target minimum tokens/sec (0 = no filter)."""
        try:
            return float(self._min_tps_combo.currentData() or "0")
        except (TypeError, ValueError):
            return 0.0

    def get_filters(self) -> dict:
        """Return current filter state as a dict for config persistence."""
        return {
            "search": self._search.text(),
            "provider": self.provider_filter,
            "usecase": self.usecase_filter,
            "fit": self.fit_filter,
            "quant": self.quant_filter,
            "license": self.license_filter,
            "capability": self.capability_filter,
            "min_tps": self._min_tps_combo.currentData() or "0",
            "installed_only": self.installed_only,
        }

    def set_filters(self, filters: dict) -> None:
        """Restore filter state from config."""
        self._search.blockSignals(True)
        self._search.setText(filters.get("search", ""))
        self._search.blockSignals(False)

        for combo, key in [
            (self._provider_combo, "provider"),
            (self._usecase_combo, "usecase"),
            (self._fit_combo, "fit"),
            (self._quant_combo, "quant"),
            (self._license_combo, "license"),
            (self._cap_combo, "capability"),
            (self._min_tps_combo, "min_tps"),
        ]:
            combo.blockSignals(True)
            idx = combo.findData(filters.get(key, ""))
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        self._installed_checkbox.blockSignals(True)
        self._installed_checkbox.setChecked(bool(filters.get("installed_only", False)))
        self._installed_checkbox.blockSignals(False)
