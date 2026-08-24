"""Installed-models view — ground truth read straight from the engines.

Unlike the catalog's "Installed" badge (which matches catalog names against an
engine's reported models and can be fuzzy), this lists exactly what Ollama and
LM Studio actually hold — including models installed outside Nameweaver — with a
per-model Remove action.
"""

from __future__ import annotations

import qtawesome as qta
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from models import _core_tokens
from provider_control import remove_model
from providers import detect_all_providers
from themes import get_theme


def _dedup_display(names: set[str]) -> list[str]:
    """Collapse an engine's model aliases to one human-friendly id per model."""
    by_key: dict = {}
    for n in names:
        size, toks = _core_tokens(n)
        # Fall back to the raw name when there are no identity tokens, so
        # distinct things (e.g. two embedding models) don't collapse together.
        key = (size, toks) if toks else ("", n.lower())
        cur = by_key.get(key)
        if cur is None:
            by_key[key] = n
            continue
        # Prefer a plain id (no 'publisher/' path); then the shorter one.
        cur_slash, n_slash = "/" in cur, "/" in n
        if (cur_slash and not n_slash) or (cur_slash == n_slash and len(n) < len(cur)):
            by_key[key] = n
    return sorted(by_key.values(), key=str.lower)


class InstalledModelsDialog(QDialog):
    """Lists actually-installed models per engine, with Remove buttons."""

    changed = pyqtSignal()  # a model was removed — caller should refresh

    def __init__(self, theme_name: str = "dark", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Installed Models")
        self.setMinimumSize(560, 480)
        self._theme_name = theme_name
        self._providers = detect_all_providers()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        header = QLabel("Models installed in your engines")
        header.setStyleSheet("font-size: 15px; font-weight: 700;")
        outer.addWidget(header)

        sub = QLabel("Read directly from Ollama / LM Studio — including models "
                     "installed outside Nameweaver.")
        sub.setWordWrap(True)
        sub.setStyleSheet("font-size: 11px;")
        outer.addWidget(sub)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self._scroll, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._reload)
        row.addWidget(refresh)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        outer.addLayout(row)

        self._populate()

    def _reload(self) -> None:
        self._providers = detect_all_providers()
        self._populate()

    def _populate(self) -> None:
        c = get_theme(self._theme_name)
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        any_model = False
        for p in self._providers:
            models = _dedup_display(getattr(p, "installed_models", set()) or set())
            if not models:
                continue
            any_model = True

            title = QLabel(f"{p.name}  ·  {len(models)}")
            title.setStyleSheet(
                f"color: {c.accent}; font-weight: 700; font-size: 12px;"
                " padding: 8px 2px 2px 2px;"
            )
            lay.addWidget(title)

            for mid in models:
                lay.addWidget(self._model_row(p.name, mid, c))

        if not any_model:
            empty = QLabel(
                "No models installed yet.\nDownload one from the catalog, "
                "or install via Ollama / LM Studio."
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {c.fg_muted}; padding: 40px;")
            lay.addWidget(empty)

        lay.addStretch(1)
        self._scroll.setWidget(container)

    def _model_row(self, engine: str, model_id: str, c) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: {c.bg_alt}; border: 1px solid {c.border};"
            f" border-radius: 8px; }}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 10, 8)

        name = QLabel(model_id)
        name.setStyleSheet(f"color: {c.fg}; background: transparent; border: none;")
        h.addWidget(name, 1)

        btn = QPushButton("Remove")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {c.error};"
            f" border: 1px solid {c.error}; border-radius: 6px; padding: 3px 12px;"
            f" font-size: 11px; font-weight: 600; }}"
            f" QPushButton:hover {{ background: {c.error}; color: {c.bg}; }}"
        )
        btn.clicked.connect(lambda _=False, e=engine, m=model_id: self._remove(e, m))
        h.addWidget(btn)
        return row

    def _remove(self, engine: str, model_id: str) -> None:
        resp = QMessageBox.question(
            self,
            "Remove model",
            f"Remove '{model_id}' from {engine}?\n\n"
            "This permanently deletes the downloaded model files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        ok, msg = remove_model(engine, model_id)
        QMessageBox.information(self, "Remove model", msg)
        if ok:
            self._reload()
            self.changed.emit()
