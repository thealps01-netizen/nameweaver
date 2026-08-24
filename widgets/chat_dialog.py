"""Simple chat dialog for streaming inference with a local LLM."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from workers import InferenceWorker


class ChatDialog(QDialog):
    """Minimal single-turn chat UI with streaming output."""

    def __init__(
        self,
        model_name: str,
        available_providers: list[str],
        parent=None,
        model_ids: dict[str, str] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Chat — {model_name}")
        self.setMinimumSize(720, 520)

        self._model_name = model_name
        # Per-provider real engine model id (e.g. Ollama 'gemma2:2b'); falls
        # back to the catalog name when unknown.
        self._model_ids = model_ids or {}
        self._worker: InferenceWorker | None = None
        self._is_running = False

        layout = QVBoxLayout(self)

        # Header row: provider picker
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Model:</b>"))
        header.addWidget(QLabel(model_name))
        header.addSpacing(24)
        header.addWidget(QLabel("<b>Provider:</b>"))
        self._provider_combo = QComboBox()
        for p in available_providers:
            self._provider_combo.addItem(p)
        header.addWidget(self._provider_combo, 1)
        layout.addLayout(header)

        # Output area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("Responses will appear here…")
        layout.addWidget(self._output, 1)

        # Prompt input
        self._input = QPlainTextEdit()
        self._input.setPlaceholderText("Type your prompt (Enter to send · Shift+Enter for newline)…")
        self._input.setFixedHeight(100)
        layout.addWidget(self._input)

        # Button row
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._clear_output)
        button_row.addWidget(self._clear_btn)

        self._send_btn = QPushButton("Send")
        self._send_btn.setDefault(True)
        self._send_btn.clicked.connect(self._send)
        button_row.addWidget(self._send_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop)
        button_row.addWidget(self._stop_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.close)
        button_row.addWidget(self._close_btn)
        layout.addLayout(button_row)

        # Ctrl+Enter shortcut
        self._input.installEventFilter(self)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent

        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # Enter sends; Shift+Enter inserts a newline.
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._send()
                    return True
        return super().eventFilter(obj, event)

    # -----------------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------------

    def _send(self):
        if self._is_running:
            return
        prompt = self._input.toPlainText().strip()
        if not prompt:
            return
        provider = self._provider_combo.currentText()
        if not provider:
            QMessageBox.warning(self, "No provider", "No provider available for this model.")
            return

        # Echo the user prompt
        self._output.append(f"<b>You:</b> {self._escape(prompt)}")
        self._output.append("<b>Assistant:</b> ")
        self._input.clear()

        self._set_running(True)

        # Send the engine's real model id, not the catalog name (avoids 404s).
        engine_model = self._model_ids.get(provider, self._model_name)
        self._worker = InferenceWorker(
            model_name=engine_model,
            provider=provider,
            prompt=prompt,
        )
        self._worker.token_received.connect(self._on_token)
        self._worker.finished_response.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()

    def _clear_output(self):
        self._output.clear()

    # -----------------------------------------------------------------------
    # Worker signal handlers
    # -----------------------------------------------------------------------

    def _on_token(self, token: str):
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(token)
        self._output.setTextCursor(cursor)
        self._output.ensureCursorVisible()

    def _on_finished(self, full: str):
        self._output.append("")  # Blank line after turn
        self._set_running(False)

    def _on_error(self, err: str):
        self._output.append(f"<span style='color:#f38ba8;'>[error: {self._escape(err)}]</span>")
        self._set_running(False)

    def _set_running(self, running: bool):
        self._is_running = running
        self._send_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._provider_combo.setEnabled(not running)

    def _escape(self, text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        super().closeEvent(event)
