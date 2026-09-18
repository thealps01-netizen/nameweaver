"""My Models — what the engines actually hold, straight from the engines.

Ground truth, not the catalog: every row comes from an engine's own report
(Ollama's /api/tags, LM Studio's OpenAI-compatible /v1/models) or, when a server
is off, from its models folder on disk. The catalog is only used to enrich a row
(name, parameters, whether it can chat) — a model that no catalog entry knows is
still listed and still runnable. That is the whole point of this view: the
catalog's "Installed" badge has to guess, and a guess is what made running a
model from its download row unreliable.

Run lives here and is the primary action; the catalog row keeps a right-click
shortcut for people who know what they want.
"""

from __future__ import annotations

import qtawesome as qta
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from providers import ProviderState, ProviderStatus
from themes import get_theme

COLUMNS = ["Model", "Engine", "Params", "Size", "Quant", "Catalog", "Chat", "Run"]

# The Run column holds a widget, not an item: the header's ResizeToContents
# measures it once and never again, so a font or padding change (the theme's
# stylesheet) left a button narrower than its own text and it rendered as "…".
# The width comes from the buttons themselves instead.
RUN_COLUMN = len(COLUMNS) - 1
RUN_COLUMN_MIN = 76


def _human_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return "—"
    gb = num_bytes / (1024**3)
    if gb >= 1:
        return f"{gb:.2f} GB"
    return f"{num_bytes / (1024**2):.0f} MB"


class MyModelsView(QWidget):
    """List of installed models, grouped by engine, with Run as the main action."""

    run_requested = pyqtSignal(str, str, str, bool)  # engine, engine model id, catalog name, chat
    remove_requested = pyqtSignal(str, str)  # engine, engine model id
    show_in_catalog_requested = pyqtSignal(str)  # catalog name
    start_engine_requested = pyqtSignal(str)  # start_action key
    refresh_requested = pyqtSignal()

    def __init__(self, theme_name: str = "dark", parent: QWidget | None = None):
        super().__init__(parent)
        self._theme_name = theme_name
        self._rows: list[dict] = []
        self._states: dict[str, ProviderStatus] = {}
        self._build()

    # ------------------------------------------------------------------ build

    def _build(self) -> None:
        c = get_theme(self._theme_name)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 0)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)

        title = QLabel("My Models")
        title.setStyleSheet(
            f"font-size: 17px; font-weight: 700; color: {c.fg}; background: transparent;"
        )
        header.addWidget(title)

        self._subtitle = QLabel("")
        self._subtitle.setStyleSheet(
            f"font-size: 12px; color: {c.fg_muted}; background: transparent;"
        )
        header.addWidget(self._subtitle)
        header.addStretch(1)

        self._refresh_btn = QPushButton("  Refresh")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setIcon(qta.icon("mdi6.refresh", color=c.fg_muted))
        self._refresh_btn.setIconSize(QSize(16, 16))
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self._refresh_btn)
        root.addLayout(header)

        self._notice = QLabel("")
        self._notice.setWordWrap(True)
        self._notice.setVisible(False)
        self._notice.setStyleSheet(f"color: {c.warning}; background: transparent; font-size: 12px;")
        root.addWidget(self._notice)

        self._engine_notices = QVBoxLayout()
        self._engine_notices.setSpacing(6)
        root.addLayout(self._engine_notices)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(COLUMNS)):
            mode = (
                QHeaderView.ResizeMode.Fixed
                if col == RUN_COLUMN
                else QHeaderView.ResizeMode.ResizeToContents
            )
            header_view.setSectionResizeMode(col, mode)
        self._table.setColumnWidth(RUN_COLUMN, RUN_COLUMN_MIN)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        card_layout.addWidget(self._table)
        root.addWidget(card, stretch=1)

        # Empty state sits on top of the table area.
        self._empty = QLabel("")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setStyleSheet(f"color: {c.fg_muted}; background: transparent; font-size: 13px;")
        self._empty.setVisible(False)
        root.addWidget(self._empty)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._remove_btn = QPushButton("Remove…")
        self._remove_btn.clicked.connect(self._on_remove_clicked)
        self._catalog_btn = QPushButton("Show in Catalog")
        self._catalog_btn.clicked.connect(self._on_show_in_catalog_clicked)
        actions.addWidget(self._remove_btn)
        actions.addWidget(self._catalog_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        self._on_selection_changed()

    # ------------------------------------------------------------- public API

    def set_theme(self, theme_name: str) -> None:
        self._theme_name = theme_name
        c = get_theme(theme_name)
        self._subtitle.setStyleSheet(
            f"font-size: 12px; color: {c.fg_muted}; background: transparent;"
        )
        self._notice.setStyleSheet(f"color: {c.warning}; background: transparent; font-size: 12px;")
        self._empty.setStyleSheet(f"color: {c.fg_muted}; background: transparent; font-size: 13px;")
        self._refresh_btn.setIcon(qta.icon("mdi6.refresh", color=c.fg_muted))
        self.set_rows(self._rows, self._states)

    def set_rows(self, rows: list[dict], states: dict[str, ProviderStatus]) -> None:
        """Render the engine-reported models.

        ``rows`` come from providers.list_installed_models(); each entry is
        {engine, id, size_bytes, parameters, quantization, path, chat, catalog,
        runnable}. ``states`` is engine name -> ProviderStatus, used for the
        per-engine notices and the Start buttons.
        """
        self._rows = list(rows)
        self._states = dict(states)
        self._render()

    # -------------------------------------------------------------- rendering

    def _render(self) -> None:
        c = get_theme(self._theme_name)
        self._table.setRowCount(0)

        engines_with_rows = {row["engine"] for row in self._rows}
        running = [name for name, st in self._states.items() if st.state == ProviderState.READY]
        engines = ", ".join(running) if running else "none"
        self._subtitle.setText(f"{len(self._rows)} model(s) · engines running: {engines}")

        self._render_engine_notices(engines_with_rows)

        for row in self._rows:
            self._append_row(row, c)

        empty = not self._rows
        self._empty.setVisible(empty)
        if empty:
            self._empty.setText(
                "No downloaded models found yet.\n"
                "Download one from the Model Catalog — it will show up here, with Run."
            )
        self._table.setVisible(not empty)
        self._on_selection_changed()
        self._fit_run_column()

    def _render_engine_notices(self, engines_with_rows: set[str]) -> None:
        """One line for the engines that need starting, one for the absent ones.

        A card per engine pushed the table down the page as soon as more than one
        engine was closed — three lines on this four-engine machine — so the off
        engines now share a line, each keeping its own Start button.
        """
        while self._engine_notices.count():
            item = self._engine_notices.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._notice.setVisible(False)

        c = get_theme(self._theme_name)
        off = [
            (name, status)
            for name, status in self._states.items()
            if status.state == ProviderState.INSTALLED_OFF and name not in engines_with_rows
        ]
        missing = [
            name
            for name, status in self._states.items()
            if status.state == ProviderState.NOT_INSTALLED and name not in engines_with_rows
        ]

        if off:
            names = ", ".join(name for name, _ in off)
            line = QFrame()
            line.setObjectName("card")
            lay = QHBoxLayout(line)
            lay.setContentsMargins(12, 8, 12, 8)
            lay.setSpacing(8)
            lbl = QLabel(
                f"{names} {'are' if len(off) > 1 else 'is'} off — start "
                f"{'them' if len(off) > 1 else 'it'} to list and run "
                f"{'their' if len(off) > 1 else 'its'} models."
            )
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color: {c.warning}; background: transparent;")
            lay.addWidget(lbl, stretch=1)
            for name, status in off:
                if not status.start_action:
                    continue
                btn = QPushButton("Start")
                btn.setToolTip(f"Start {name}")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(
                    lambda _=False, a=status.start_action: self.start_engine_requested.emit(a)
                )
                lay.addWidget(btn)
            self._engine_notices.addWidget(line)

        if missing:
            lbl = QLabel(f"Not installed: {', '.join(missing)}.")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color: {c.fg_muted}; background: transparent; font-size: 11px;")
            self._engine_notices.addWidget(lbl)

    def _fit_run_column(self) -> None:
        """Give the Run column the width its own buttons ask for.

        A cell widget's size hint already carries the text, the font and the
        padding, so measuring the built buttons is the only width that cannot
        elide them.
        """
        hints = [
            widget.sizeHint().width()
            for row in range(self._table.rowCount())
            if (widget := self._table.cellWidget(row, RUN_COLUMN)) is not None
        ]
        self._table.setColumnWidth(RUN_COLUMN, max([RUN_COLUMN_MIN, *hints]) + 8)

    def _append_row(self, row: dict, c) -> None:
        r = self._table.rowCount()
        self._table.insertRow(r)

        display = row.get("catalog") or row["id"]
        name_item = QTableWidgetItem(display)
        name_item.setToolTip(row["id"])
        if row.get("catalog"):
            name_item.setForeground(Qt.GlobalColor.gray)
        self._table.setItem(r, 0, name_item)

        self._table.setItem(r, 1, QTableWidgetItem(row["engine"]))
        self._table.setItem(r, 2, QTableWidgetItem(row.get("parameters") or "—"))
        self._table.setItem(r, 3, QTableWidgetItem(_human_size(row.get("size_bytes", 0))))
        self._table.setItem(r, 4, QTableWidgetItem(row.get("quantization") or "—"))

        catalog_item = QTableWidgetItem(row.get("catalog") or "—")
        if not row.get("catalog"):
            catalog_item.setToolTip("Not in the catalog — the engine still lists it")
        self._table.setItem(r, 5, catalog_item)

        chat = row.get("chat")
        chat_text = "yes" if chat else ("no" if chat is False else "?")
        chat_item = QTableWidgetItem(chat_text)
        if chat is False:
            chat_item.setToolTip("This is an embedding model — it cannot hold a chat")
        elif chat is None:
            chat_item.setToolTip("The engine did not say; try Run")
        self._table.setItem(r, 6, chat_item)

        btn = QPushButton("Run")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        can_run = bool(row.get("runnable", True)) and row.get("chat") is not False
        btn.setEnabled(can_run)
        if not can_run:
            btn.setToolTip(
                "This is an embedding model — it cannot hold a chat"
                if row.get("chat") is False
                else "Start the engine first"
            )
        btn.clicked.connect(
            lambda _=False, payload=dict(row): self.run_requested.emit(
                payload["engine"],
                payload["id"],
                payload.get("catalog") or "",
                bool(payload.get("chat")),
            )
        )
        self._table.setCellWidget(r, 7, btn)

    # ----------------------------------------------------------------- events

    def _selected_row(self) -> dict | None:
        rows = {i.row() for i in self._table.selectedItems()}
        if not rows:
            return None
        index = sorted(rows)[0]
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def _on_selection_changed(self) -> None:
        row = self._selected_row()
        self._remove_btn.setEnabled(row is not None)
        self._remove_btn.setToolTip(
            "" if row is not None else "Select a row first — removal deletes its files"
        )
        has_catalog = bool(row and row.get("catalog"))
        self._catalog_btn.setEnabled(has_catalog)
        self._catalog_btn.setToolTip(
            "" if has_catalog else "Select a row that is also in the catalog"
        )

    def _on_remove_clicked(self) -> None:
        row = self._selected_row()
        if row is not None:
            self.remove_requested.emit(row["engine"], row["id"])

    def _on_show_in_catalog_clicked(self) -> None:
        row = self._selected_row()
        if row is not None and row.get("catalog"):
            self.show_in_catalog_requested.emit(row["catalog"])

    def select_model(self, name: str) -> bool:
        """Select the row for a catalog model (or engine id); False if not listed."""
        for index, row in enumerate(self._rows):
            if row.get("catalog") == name or row.get("id") == name:
                self._table.selectRow(index)
                return True
        return False

    # ------------------------------------------------------------------ tests

    def row_count(self) -> int:
        return self._table.rowCount()

    def cell_text(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return item.text() if item is not None else ""

    def run_button(self, row: int) -> QPushButton | None:
        widget = self._table.cellWidget(row, 7)
        return widget if isinstance(widget, QPushButton) else None
