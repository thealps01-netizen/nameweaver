"""Custom status bar widget."""

from PyQt6.QtWidgets import QLabel, QStatusBar


class AppStatusBar(QStatusBar):
    """Status bar showing theme, model count, version, and HW sim status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_label = QLabel("Dark Theme")
        self._model_count_label = QLabel("0 models")
        self._hwsim_label = QLabel("HW Sim: OFF")

        self.addWidget(self._theme_label)
        self.addWidget(self._separator())
        self.addWidget(self._model_count_label)
        self.addWidget(self._separator())
        self.addWidget(self._hwsim_label)

    def _separator(self) -> QLabel:
        sep = QLabel("|")
        sep.setProperty("class", "muted")
        return sep

    def set_theme_name(self, name: str):
        self._theme_label.setText(f"{name.capitalize()} Theme")

    def set_model_count(self, total: int, visible: int | None = None):
        if visible is not None and visible != total:
            self._model_count_label.setText(f"{visible}/{total} models")
        else:
            self._model_count_label.setText(f"{total} models")

    def set_version(self, version: str):
        pass  # version shown in header badge

    def set_hw_sim(self, active: bool):
        self._hwsim_label.setText(f"HW Sim: {'ON' if active else 'OFF'}")
