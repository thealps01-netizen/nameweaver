"""Rich chat dialog: bubble transcript, markdown + code blocks with copy,
per-message actions, streaming indicator, image upload (vision), tok/s stats,
and conversation controls — over local engines."""

from __future__ import annotations

import base64
import html
import re
import time

import qtawesome as qta
from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from themes import get_theme
from widgets.markdown_render import md_to_html, split_segments
from workers import InferenceWorker

_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_BUBBLE_MAX_WIDTH = 560


def _highlight_code(code: str, lang: str) -> str | None:
    """Return highlighted inline-styled HTML for code, or None to fall back."""
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name, guess_lexer
    except Exception:
        return None
    try:
        lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
    except Exception:
        try:
            lexer = guess_lexer(code)
        except Exception:
            return None
    fmt = HtmlFormatter(noclasses=True, nowrap=True, style="monokai")
    try:
        return highlight(code, lexer, fmt)
    except Exception:
        return None


class _CodeBlock(QFrame):
    """A code block: monospace body (+optional highlight) with a Copy button."""

    def __init__(self, code: str, lang: str, theme, parent=None):
        super().__init__(parent)
        self._code = code
        c = theme
        self.setStyleSheet(
            f"QFrame {{ background:{c.bg}; border:1px solid {c.border};"
            f" border-radius:8px; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(10, 4, 6, 4)
        tag = QLabel(lang or "code")
        tag.setStyleSheet(f"color:{c.fg_muted}; font-size:10px; background:transparent; border:none;")
        bar.addWidget(tag)
        bar.addStretch(1)
        copy = QPushButton("Copy")
        copy.setCursor(Qt.CursorShape.PointingHandCursor)
        copy.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{c.fg_muted};"
            f" border:none; font-size:10px; }} QPushButton:hover {{ color:{c.accent}; }}"
        )
        copy.clicked.connect(self._copy)
        bar.addWidget(copy)
        lay.addLayout(bar)

        body = QLabel()
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setWordWrap(True)
        hl = _highlight_code(code, lang)
        if hl is not None:
            body.setTextFormat(Qt.TextFormat.RichText)
            body.setText(
                f'<pre style="margin:0; font-family:Consolas,monospace;'
                f' white-space:pre-wrap;">{hl}</pre>'
            )
        else:
            body.setTextFormat(Qt.TextFormat.RichText)
            body.setText(
                f'<pre style="margin:0; color:{c.fg}; font-family:Consolas,monospace;'
                f' white-space:pre-wrap;">{html.escape(code)}</pre>'
            )
        body.setStyleSheet("background:transparent; border:none; padding:8px 10px;")
        lay.addWidget(body)

    def _copy(self):
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self._code)


class _Bubble(QFrame):
    """One chat message bubble (avatar + content + optional action row)."""

    def __init__(self, role: str, theme, on_copy=None, on_regen=None,
                 on_feedback=None, parent=None):
        super().__init__(parent)
        self._role = role
        self._theme = theme
        self._on_copy = on_copy
        self._on_regen = on_regen
        self._on_feedback = on_feedback
        c = theme
        is_user = role == "user"
        bg = c.accent if is_user else c.bg_alt
        fg = c.accent_text if is_user else c.fg
        self._fg = fg
        self.setMaximumWidth(_BUBBLE_MAX_WIDTH)
        self.setStyleSheet(
            f"QFrame#bubble {{ background:{bg}; border-radius:12px; }}"
            f" QLabel {{ color:{fg}; background:transparent; border:none; }}"
        )
        self.setObjectName("bubble")

        # Subtle drop shadow for depth.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(shadow)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(14, 11, 14, 11)
        self._lay.setSpacing(7)

        # Header: avatar + role name + timestamp
        head = QHBoxLayout()
        head.setSpacing(7)
        avatar = QLabel()
        icon = "mdi6.account" if is_user else "mdi6.robot-happy-outline"
        avatar.setPixmap(qta.icon(icon, color=(fg if is_user else c.good)).pixmap(QSize(18, 18)))
        avatar.setStyleSheet("background:transparent; border:none;")
        who = QLabel("You" if is_user else "Assistant")
        who.setStyleSheet(
            f"color:{fg if is_user else c.good}; font-weight:700; font-size:11px;"
            " background:transparent; border:none;"
        )
        ts = QLabel(time.strftime("%H:%M"))
        ts.setStyleSheet(
            f"color:{fg if is_user else c.fg_muted}; font-size:10px;"
            " background:transparent; border:none;"
        )
        if is_user:
            head.addStretch(1)
            head.addWidget(ts)
            head.addWidget(who)
            head.addWidget(avatar)
        else:
            head.addWidget(avatar)
            head.addWidget(who)
            head.addStretch(1)
            head.addWidget(ts)
        self._lay.addLayout(head)

        self._content_holder = QVBoxLayout()
        self._content_holder.setSpacing(6)
        self._lay.addLayout(self._content_holder)

        # Action row (assistant only), shown after a completed response.
        self._actions = QWidget()
        arow = QHBoxLayout(self._actions)
        arow.setContentsMargins(0, 2, 0, 0)
        arow.setSpacing(8)
        if not is_user:
            for icon, tip, cb in (
                ("mdi6.content-copy", "Copy", self._do_copy),
                ("mdi6.refresh", "Regenerate", self._do_regen),
                ("mdi6.thumb-up-outline", "Good", lambda: self._fb("up")),
                ("mdi6.thumb-down-outline", "Bad", lambda: self._fb("down")),
            ):
                b = QPushButton()
                b.setIcon(qta.icon(icon, color=c.fg_muted))
                b.setIconSize(QSize(14, 14))
                b.setToolTip(tip)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setFlat(True)
                b.setStyleSheet("QPushButton{background:transparent;border:none;}")
                b.clicked.connect(cb)
                arow.addWidget(b)
        arow.addStretch(1)
        self._actions.setVisible(False)
        self._lay.addWidget(self._actions)

        self._text = ""  # raw text (for copy)

    # ---- content ----
    def _clear_content(self):
        while self._content_holder.count():
            item = self._content_holder.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def set_thinking(self, frame: int):
        """Animated 'typing' dots shown until the first token arrives."""
        self._clear_content()
        dots = "●" * (1 + frame % 3)
        lbl = QLabel(dots)
        lbl.setStyleSheet(
            f"color:{self._theme.good}; font-size:16px; letter-spacing:3px;"
            " background:transparent; border:none;"
        )
        self._content_holder.addWidget(lbl)

    def set_plain(self, text: str, cursor: bool = False):
        """Live streaming text (plain, no markdown)."""
        self._text = text
        self._clear_content()
        lbl = QLabel()
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        shown = html.escape(text) + ("▌" if cursor else "")
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setText(shown.replace("\n", "<br>"))
        self._content_holder.addWidget(lbl)

    def set_segments(self, text: str, images: int = 0):
        """Final rendered content: markdown text + code blocks."""
        self._text = text
        self._clear_content()
        if images:
            img = QLabel(f"🖼 {images} image(s)")
            img.setStyleSheet(f"color:{self._theme.fg_muted}; font-style:italic;")
            self._content_holder.addWidget(img)
        for kind, content, lang in split_segments(text):
            if kind == "code":
                self._content_holder.addWidget(_CodeBlock(content, lang, self._theme))
            else:
                if not content.strip():
                    continue
                lbl = QLabel()
                lbl.setWordWrap(True)
                lbl.setOpenExternalLinks(True)
                lbl.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.LinksAccessibleByMouse
                )
                lbl.setTextFormat(Qt.TextFormat.RichText)
                lbl.setText(md_to_html(content))
                self._content_holder.addWidget(lbl)
        if self._role == "assistant":
            self._actions.setVisible(True)

    def _do_copy(self):
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self._text)

    def _do_regen(self):
        if self._on_regen:
            self._on_regen()

    def _fb(self, kind):
        if self._on_feedback:
            self._on_feedback(kind)


class ChatDialog(QDialog):
    """Multi-turn chat with bubbles, markdown, images and controls."""

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
        self.setMinimumSize(780, 640)

        self._model_name = model_name
        self._model_ids = model_ids or {}
        self._supports_vision = supports_vision
        self._theme = get_theme(theme_name)
        self._worker: InferenceWorker | None = None
        self._is_running = False

        self._history: list[dict] = []
        self._pending_images: list[str] = []
        self._stream_buf: list[str] = []
        self._stream_bubble: _Bubble | None = None
        self._stream_started = 0.0
        self._cursor_on = True
        self._got_first_token = False
        self._think_frame = 0

        c = self._theme
        root = QVBoxLayout(self)

        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel(f"<b>Model:</b> {html.escape(model_name)}"))
        header.addSpacing(16)
        header.addWidget(QLabel("<b>Engine:</b>"))
        self._provider_combo = QComboBox()
        for p in available_providers:
            self._provider_combo.addItem(p)
        header.addWidget(self._provider_combo, 1)
        self._stats = QLabel("")
        self._stats.setStyleSheet(f"color:{c.fg_muted}; font-size:11px;")
        header.addWidget(self._stats)
        root.addLayout(header)

        # System prompt
        self._system = QLineEdit()
        self._system.setPlaceholderText("System prompt (optional) — e.g. 'Always answer in Turkish.'")
        root.addWidget(self._system)

        # Transcript scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background:{c.bg}; border:1px solid {c.border};"
            f" border-radius:10px; }}"
        )
        self._msg_container = QWidget()
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(14, 14, 14, 14)
        self._msg_layout.setSpacing(16)
        self._msg_layout.addStretch(1)  # keep messages pushed up
        self._scroll.setWidget(self._msg_container)
        root.addWidget(self._scroll, 1)

        self._empty = QLabel(
            f"💬  Chatting with <b>{html.escape(model_name)}</b><br>"
            "Ask anything." + (" You can attach an image (📎)." if supports_vision else "")
        )
        self._empty.setTextFormat(Qt.TextFormat.RichText)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(f"color:{c.fg_muted}; padding:40px;")
        self._msg_layout.insertWidget(0, self._empty)

        # Attached-image indicator
        self._img_bar = QLabel("")
        self._img_bar.setStyleSheet(f"color:{c.fg_muted}; font-size:11px;")
        self._img_bar.setVisible(False)
        root.addWidget(self._img_bar)

        # Input
        self._input = QPlainTextEdit()
        self._input.setPlaceholderText("Type your prompt (Enter to send · Shift+Enter for newline)…")
        self._input.setFixedHeight(56)
        self._input.installEventFilter(self)
        self._input.setStyleSheet(
            f"QPlainTextEdit {{ background:{c.bg_alt}; color:{c.fg};"
            f" border:1px solid {c.border}; border-radius:12px; padding:8px 12px; }}"
            f" QPlainTextEdit:focus {{ border-color:{c.accent}; }}"
        )
        self._input.textChanged.connect(self._adjust_input_height)
        root.addWidget(self._input)

        # Action row
        row = QHBoxLayout()
        self._attach_btn = QPushButton(" Image")
        self._attach_btn.setIcon(qta.icon("mdi6.image-outline", color=c.fg_muted))
        self._attach_btn.setToolTip(
            "Attach an image (or drag & drop). Best with vision models."
        )
        self._attach_btn.clicked.connect(self._attach_image)
        row.addWidget(self._attach_btn)
        self._vision_warned = False
        self.setAcceptDrops(True)  # drag & drop images anywhere on the dialog

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._clear_chat)
        row.addWidget(self._clear_btn)
        row.addStretch(1)

        self._send_btn = QPushButton(" Send")
        self._send_btn.setIcon(qta.icon("mdi6.send", color=c.accent_text))
        self._send_btn.clicked.connect(self._send)
        row.addWidget(self._send_btn)
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop)
        row.addWidget(self._stop_btn)
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.close)
        row.addWidget(self._close_btn)
        root.addLayout(row)

        # Blinking cursor timer for the streaming bubble.
        self._blink = QTimer(self)
        self._blink.setInterval(500)
        self._blink.timeout.connect(self._tick_cursor)

    # --------------------------------------------------------------- input
    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent

        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._send()
                    return True
        return super().eventFilter(obj, event)

    def _adjust_input_height(self):
        doc_h = self._input.document().size().height()
        target = int(doc_h) + 20
        self._input.setFixedHeight(max(56, min(target, 170)))

    def _attach_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach image", "", "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp)"
        )
        if path:
            self._add_image_from_path(path)

    def _add_image_from_path(self, path: str):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            QMessageBox.warning(self, "Image", f"Could not read image:\n{exc}")
            return
        if len(data) > _MAX_IMAGE_BYTES:
            QMessageBox.warning(self, "Image", "Image is too large (max 12 MB).")
            return
        if not self._supports_vision and not self._vision_warned:
            self._vision_warned = True
            QMessageBox.information(
                self, "Image",
                "This model isn't detected as a vision model, so it may ignore "
                "the image. Attaching anyway — use a vision model (e.g. "
                "qwen2.5vl, llava, gemma3-vision) to actually read images.",
            )
        self._pending_images.append(base64.b64encode(data).decode("ascii"))
        n = len(self._pending_images)
        self._img_bar.setText(f"🖼 {n} image(s) attached — sent with your next message")
        self._img_bar.setVisible(True)

    _IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and p.lower().endswith(self._IMG_EXTS):
                self._add_image_from_path(p)
        event.acceptProposedAction()

    # ------------------------------------------------------------ transcript
    def _at_bottom(self) -> bool:
        sb = self._scroll.verticalScrollBar()
        return sb.value() >= sb.maximum() - 8

    def _scroll_to_end(self):
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()))

    def _add_bubble(self, role: str) -> _Bubble:
        self._empty.setVisible(False)
        bubble = _Bubble(role, self._theme, on_regen=self._regenerate,
                         on_feedback=self._on_feedback)
        roww = QWidget()
        rl = QHBoxLayout(roww)
        rl.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            rl.addStretch(1)
            rl.addWidget(bubble)
        else:
            rl.addWidget(bubble)
            rl.addStretch(1)
        # insert before the trailing stretch
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, roww)
        return bubble

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

        b = self._add_bubble("user")
        b.set_segments(prompt, images=len(self._pending_images))
        self._pending_images = []
        self._img_bar.setVisible(False)
        self._input.clear()
        self._scroll_to_end()
        self._start_stream()

    def _start_stream(self):
        self._set_running(True)
        self._stream_buf = []
        self._stream_started = time.monotonic()
        self._got_first_token = False
        self._think_frame = 0
        self._stream_bubble = self._add_bubble("assistant")
        self._stream_bubble.set_thinking(0)  # "typing…" until first token
        self._blink.setInterval(350)
        self._blink.start()
        self._scroll_to_end()

        provider = self._provider_combo.currentText()
        engine_model = self._model_ids.get(provider, self._model_name)
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

    def _tick_cursor(self):
        if self._stream_bubble is None:
            return
        if not self._got_first_token:
            # Animated "thinking" dots before any text arrives.
            self._think_frame += 1
            self._stream_bubble.set_thinking(self._think_frame)
            return
        self._cursor_on = not self._cursor_on
        self._stream_bubble.set_plain("".join(self._stream_buf), cursor=self._cursor_on)

    def _on_token(self, token: str):
        at_bottom = self._at_bottom()
        self._got_first_token = True
        self._stream_buf.append(token)
        if self._stream_bubble is not None:
            self._stream_bubble.set_plain("".join(self._stream_buf), cursor=True)
        n = len("".join(self._stream_buf).split())
        dt = max(time.monotonic() - self._stream_started, 0.001)
        self._stats.setText(f"~{n / dt:.0f} tok/s")
        if at_bottom:
            self._scroll_to_end()

    def _on_finished(self, full: str):
        self._blink.stop()
        text = full or "".join(self._stream_buf)
        self._history.append({"role": "assistant", "content": text})
        if self._stream_bubble is not None:
            self._stream_bubble.set_segments(text)
        self._stream_bubble = None
        dt = max(time.monotonic() - self._stream_started, 0.001)
        words = len(text.split())
        self._stats.setText(f"{words} words · ~{words / dt:.0f} tok/s")
        self._set_running(False)

    def _on_error(self, err: str):
        self._blink.stop()
        self._history.append({"role": "assistant", "content": f"[error: {err}]"})
        if self._stream_bubble is not None:
            self._stream_bubble.set_segments(f"[error: {err}]")
        self._stream_bubble = None
        self._set_running(False)

    def _stop(self):
        if self._worker:
            self._worker.cancel()

    def _set_running(self, running: bool):
        self._is_running = running
        self._send_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        self._provider_combo.setEnabled(not running)
        self._clear_btn.setEnabled(not running)

    # -------------------------------------------------------------- controls
    def _clear_chat(self):
        if self._is_running:
            return
        self._history = []
        self._pending_images = []
        self._img_bar.setVisible(False)
        self._stats.setText("")
        # Remove all message rows (keep the trailing stretch).
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            w = item.widget()
            if w and w is not self._empty:
                w.deleteLater()
        self._msg_layout.insertWidget(0, self._empty)
        self._empty.setVisible(True)

    def _regenerate(self):
        if self._is_running or not self._history:
            return
        if self._history[-1]["role"] == "assistant":
            self._history.pop()
            # drop the last assistant bubble row
            idx = self._msg_layout.count() - 2  # before stretch
            if idx >= 0:
                item = self._msg_layout.takeAt(idx)
                w = item.widget()
                if w:
                    w.deleteLater()
        if not self._history or self._history[-1]["role"] != "user":
            return
        self._start_stream()

    def _on_feedback(self, kind: str):
        import logging
        logging.getLogger(__name__).info("Chat feedback: %s", kind)

    def closeEvent(self, event):
        self._blink.stop()
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(1500)
        event.accept()
