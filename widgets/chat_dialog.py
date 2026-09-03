"""Rich chat dialog: multi-turn history, markdown/code rendering, image
upload for vision models, and conversation controls — over local engines."""

from __future__ import annotations

import base64
import html
import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from themes import get_theme
from workers import InferenceWorker

_MAX_IMAGE_BYTES = 12 * 1024 * 1024  # 12 MB safety cap per image


def _md_to_html(text: str, mono_bg: str, mono_fg: str) -> str:
    """Minimal, safe Markdown → HTML (code blocks, inline code, bold/italic)."""
    placeholders: list[str] = []

    def _stash(html_fragment: str) -> str:
        placeholders.append(html_fragment)
        return f"\x00{len(placeholders) - 1}\x00"

    # Fenced code blocks ```lang\n...\n```
    def _code_block(m: re.Match) -> str:
        code = html.escape(m.group(2))
        return _stash(
            f'<pre style="background:{mono_bg}; color:{mono_fg}; padding:8px;'
            f' border-radius:6px; white-space:pre-wrap;">{code}</pre>'
        )

    text = re.sub(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", _code_block, text, flags=re.DOTALL)

    # Inline code `x`
    def _inline_code(m: re.Match) -> str:
        return _stash(
            f'<code style="background:{mono_bg}; color:{mono_fg};'
            f' padding:1px 4px; border-radius:4px;">{html.escape(m.group(1))}</code>'
        )

    text = re.sub(r"`([^`\n]+)`", _inline_code, text)

    # Escape the remaining text, then apply light inline formatting.
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", text)
    text = text.replace("\n", "<br>")

    # Restore code placeholders.
    for i, frag in enumerate(placeholders):
        text = text.replace(f"\x00{i}\x00", frag)
    return text


class ChatDialog(QDialog):
    """Multi-turn chat with markdown, images (vision models) and controls."""

    def __init__(
        self,
        model_name: str,
        available_providers: list[str],
        parent=None,
        model_ids: dict[str, str] | None = None,
        supports_vision: bool = False,
        theme_name: str = "dark",
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Chat — {model_name}")
        self.setMinimumSize(760, 600)

        self._model_name = model_name
        self._model_ids = model_ids or {}
        self._supports_vision = supports_vision
        self._theme = get_theme(theme_name)
        self._worker: InferenceWorker | None = None
        self._is_running = False

        # Conversation state: list of {role, content, images:[b64]}.
        self._history: list[dict] = []
        self._pending_images: list[str] = []  # base64 for the next user turn
        self._stream_buf: list[str] = []

        c = self._theme
        layout = QVBoxLayout(self)

        # Header: model + provider picker
        header = QHBoxLayout()
        header.addWidget(QLabel(f"<b>Model:</b> {html.escape(model_name)}"))
        header.addSpacing(16)
        header.addWidget(QLabel("<b>Engine:</b>"))
        self._provider_combo = QComboBox()
        for p in available_providers:
            self._provider_combo.addItem(p)
        header.addWidget(self._provider_combo, 1)
        layout.addLayout(header)

        # System prompt (optional)
        self._system = QLineEdit()
        self._system.setPlaceholderText("System prompt (optional) — how the assistant should behave")
        layout.addWidget(self._system)

        # Transcript
        self._output = QTextBrowser()
        self._output.setOpenExternalLinks(True)
        self._output.setStyleSheet(
            f"QTextBrowser {{ background:{c.bg_alt}; color:{c.fg};"
            f" border:1px solid {c.border}; border-radius:8px; padding:8px; }}"
        )
        layout.addWidget(self._output, 1)

        # Attached-image chips
        self._img_bar = QLabel("")
        self._img_bar.setStyleSheet(f"color:{c.fg_muted}; font-size:11px;")
        self._img_bar.setVisible(False)
        layout.addWidget(self._img_bar)

        # Prompt input
        self._input = QPlainTextEdit()
        self._input.setPlaceholderText("Type your prompt (Enter to send · Shift+Enter for newline)…")
        self._input.setFixedHeight(90)
        self._input.installEventFilter(self)
        layout.addWidget(self._input)

        # Action row
        row = QHBoxLayout()
        self._attach_btn = QPushButton("📎 Image")
        self._attach_btn.setToolTip(
            "Attach an image" if self._supports_vision
            else "This model can't see images (not a vision model)"
        )
        self._attach_btn.setEnabled(self._supports_vision)
        self._attach_btn.clicked.connect(self._attach_image)
        row.addWidget(self._attach_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._clear_chat)
        row.addWidget(self._clear_btn)

        self._regen_btn = QPushButton("Regenerate")
        self._regen_btn.clicked.connect(self._regenerate)
        row.addWidget(self._regen_btn)

        self._copy_btn = QPushButton("Copy last")
        self._copy_btn.clicked.connect(self._copy_last)
        row.addWidget(self._copy_btn)

        row.addStretch(1)
        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._send)
        row.addWidget(self._send_btn)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop)
        row.addWidget(self._stop_btn)
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.close)
        row.addWidget(self._close_btn)
        layout.addLayout(row)

        self._render()

    # ------------------------------------------------------------------ input
    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent

        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._send()
                    return True
        return super().eventFilter(obj, event)

    def _attach_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach image", "", "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp)"
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            QMessageBox.warning(self, "Image", f"Could not read image:\n{exc}")
            return
        if len(data) > _MAX_IMAGE_BYTES:
            QMessageBox.warning(self, "Image", "Image is too large (max 12 MB).")
            return
        self._pending_images.append(base64.b64encode(data).decode("ascii"))
        self._update_image_bar()

    def _update_image_bar(self):
        n = len(self._pending_images)
        if n:
            self._img_bar.setText(f"🖼 {n} image(s) attached — will be sent with your next message  (click Clear to drop)")
            self._img_bar.setVisible(True)
        else:
            self._img_bar.setVisible(False)

    # --------------------------------------------------------------- rendering
    def _render(self):
        c = self._theme
        parts = []
        for m in self._history:
            role = m["role"]
            if role == "system":
                continue
            label = "You" if role == "user" else "Assistant"
            color = c.accent if role == "user" else c.good
            body = _md_to_html(m.get("content", ""), c.bg, c.fg)
            if m.get("images"):
                body = f'<i style="color:{c.fg_muted};">🖼 {len(m["images"])} image(s)</i><br>' + body
            parts.append(
                f'<div style="margin:6px 0;"><b style="color:{color};">{label}</b>'
                f'<br>{body}</div>'
            )
        self._output.setHtml("".join(parts))
        self._scroll_to_end()

    def _scroll_to_end(self):
        sb = self._output.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ------------------------------------------------------------------ chat
    def _send(self):
        if self._is_running:
            return
        prompt = self._input.toPlainText().strip()
        if not prompt and not self._pending_images:
            return

        user_msg = {"role": "user", "content": prompt}
        if self._pending_images:
            user_msg["images"] = list(self._pending_images)
        self._history.append(user_msg)
        self._pending_images = []
        self._update_image_bar()
        self._input.clear()
        self._start_stream()

    def _start_stream(self):
        self._set_running(True)
        self._render()

        # Live streaming block (plain text; re-rendered as markdown on finish).
        cur = self._output.textCursor()
        cur.movePosition(QTextCursor.MovePosition.End)
        cur.insertHtml(f'<div><b style="color:{self._theme.good};">Assistant</b><br></div>')
        self._output.setTextCursor(cur)
        self._stream_buf = []

        provider = self._provider_combo.currentText()
        engine_model = self._model_ids.get(provider, self._model_name)

        # Full message list: system (if any) + conversation history.
        messages: list[dict] = []
        sys_prompt = self._system.text().strip()
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.extend(self._history)

        self._worker = InferenceWorker(
            model_name=engine_model, provider=provider, messages=messages
        )
        self._worker.token_received.connect(self._on_token)
        self._worker.finished_response.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_token(self, token: str):
        self._stream_buf.append(token)
        cur = self._output.textCursor()
        cur.movePosition(QTextCursor.MovePosition.End)
        cur.insertText(token)
        self._output.setTextCursor(cur)
        self._scroll_to_end()

    def _on_finished(self, full: str):
        text = full or "".join(self._stream_buf)
        self._history.append({"role": "assistant", "content": text})
        self._set_running(False)
        self._render()  # re-render with markdown

    def _on_error(self, err: str):
        self._history.append({"role": "assistant", "content": f"[error: {err}]"})
        self._set_running(False)
        self._render()

    def _stop(self):
        if self._worker:
            self._worker.cancel()

    def _set_running(self, running: bool):
        self._is_running = running
        self._send_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._provider_combo.setEnabled(not running)
        self._regen_btn.setEnabled(not running)
        self._clear_btn.setEnabled(not running)

    # -------------------------------------------------------------- controls
    def _clear_chat(self):
        if self._is_running:
            return
        self._history = []
        self._pending_images = []
        self._update_image_bar()
        self._render()

    def _regenerate(self):
        """Drop the last assistant reply and re-run the last user turn."""
        if self._is_running or not self._history:
            return
        if self._history and self._history[-1]["role"] == "assistant":
            self._history.pop()
        if not self._history or self._history[-1]["role"] != "user":
            return
        self._start_stream()

    def _copy_last(self):
        from PyQt6.QtWidgets import QApplication

        last = next((m for m in reversed(self._history) if m["role"] == "assistant"), None)
        if last:
            cb = QApplication.clipboard()
            if cb:
                cb.setText(last.get("content", ""))

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(1500)
        event.accept()
