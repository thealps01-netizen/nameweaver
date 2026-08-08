"""Application dialogs — About, etc."""

import qtawesome as qta
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from themes import get_theme
from version import __version__


class AboutDialog(QDialog):
    """About dialog showing application info."""

    # Emitted when the user clicks "Check for updates".
    check_updates_requested = pyqtSignal()

    def __init__(self, theme_name: str = "dark", parent=None):
        super().__init__(parent)
        self._theme = get_theme(theme_name)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(440, 400)
        self._drag_pos = None
        self._setup_ui()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.pos().y() < 60:
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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

        container = QFrame()
        container.setObjectName("about_container")
        container.setStyleSheet(
            f"QFrame#about_container {{ background: {c.bg}; border: 1px solid {c.accent};"
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
        layout.setSpacing(10)
        layout.setContentsMargins(28, 24, 28, 24)

        # Header row
        _ah = c.accent.lstrip("#")
        _ar, _ag, _ab = int(_ah[0:2], 16), int(_ah[2:4], 16), int(_ah[4:6], 16)
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 rgba({_ar},{_ag},{_ab},0.2), stop:1 transparent);"
            f" border-radius: 8px; padding: 8px; }}"
        )
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 8, 12, 8)
        h_layout.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("mdi6.head-snowflake-outline", color=c.accent).pixmap(QSize(40, 40)))
        icon_lbl.setFixedSize(44, 44)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        h_layout.addWidget(icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Nameweaver")
        title.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {c.fg}; background: transparent; border: none;")
        title_col.addWidget(title)
        version = QLabel(f"v{__version__}")
        version.setStyleSheet(f"font-size: 11px; color: {c.fg_muted}; background: transparent; border: none;")
        title_col.addWidget(version)
        h_layout.addLayout(title_col)
        h_layout.addStretch()

        close_btn = QPushButton()
        close_btn.setIcon(qta.icon("mdi6.close", color=c.fg_muted))
        close_btn.setIconSize(QSize(24, 24))
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: rgba(255,80,80,0.25); }}"
        )
        close_btn.clicked.connect(self.close)
        h_layout.addWidget(close_btn)
        layout.addWidget(header)

        # Description
        desc = QLabel(
            "Right-size LLM models to your hardware.\n\n"
            "Detects your system\u2019s RAM, CPU, and GPU, then scores\n"
            "each model across quality, speed, fit, and context\n"
            "dimensions to tell you which ones will run well."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {c.fg}; font-size: 12px; line-height: 1.5; background: transparent;")
        layout.addWidget(desc)

        # Credits
        credits = QLabel(
            f'Based on <a style="color:{c.accent}" href="https://github.com/AlexsJones/llmfit">llmfit</a> by Alex Jones'
        )
        credits.setOpenExternalLinks(True)
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits.setStyleSheet(f"color: {c.fg_muted}; font-size: 11px; background: transparent;")
        layout.addWidget(credits)

        layout.addStretch()

        # Check-for-updates button
        _ah2 = c.accent.lstrip("#")
        _r2, _g2, _b2 = int(_ah2[0:2], 16), int(_ah2[2:4], 16), int(_ah2[4:6], 16)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        update_btn = QPushButton("  Güncellemeleri Denetle")
        update_btn.setIcon(qta.icon("mdi6.cloud-download-outline", color=c.bg))
        update_btn.setIconSize(QSize(18, 18))
        update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        update_btn.setFixedHeight(36)
        update_btn.setStyleSheet(
            f"QPushButton {{ background: {c.accent}; color: {c.bg}; border: none;"
            f" border-radius: 6px; font-weight: bold; font-size: 13px; padding: 0 18px; }}"
            f"QPushButton:hover {{ background: rgba({_r2},{_g2},{_b2},0.8); }}"
        )
        update_btn.clicked.connect(self._on_check_updates)
        btn_row.addWidget(update_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        outer.addWidget(container)

    def _on_check_updates(self):
        """Close the dialog and ask the main window to run an update check."""
        self.check_updates_requested.emit()
        self.close()


class AlertDialog(QDialog):
    """Custom styled alert dialog."""

    def __init__(self, title: str, text: str, theme_name: str = "dark", parent=None):
        super().__init__(parent)
        self._theme = get_theme(theme_name)
        self._title = title
        self._text = text
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(400, 220)
        self._drag_pos = None
        self._setup_ui()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.pos().y() < 60:
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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

        container = QFrame()
        container.setObjectName("alert_container")
        container.setStyleSheet(
            f"QFrame#alert_container {{ background: {c.bg}; border: 1px solid {c.accent};"
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
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header 
        _ah = c.accent.lstrip("#")
        _ar, _ag, _ab = int(_ah[0:2], 16), int(_ah[2:4], 16), int(_ah[4:6], 16)
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 rgba({_ar},{_ag},{_ab},0.2), stop:1 transparent);"
            f" border-radius: 8px; padding: 4px; }}"
        )
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 4, 12, 4)
        h_layout.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("mdi6.alert-circle-outline", color=c.accent).pixmap(QSize(32, 32)))
        icon_lbl.setFixedSize(36, 36)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        h_layout.addWidget(icon_lbl)

        title = QLabel(self._title)
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {c.fg}; background: transparent; border: none;")
        h_layout.addWidget(title)
        h_layout.addStretch()

        close_btn = QPushButton()
        close_btn.setIcon(qta.icon("mdi6.close", color=c.fg_muted))
        close_btn.setIconSize(QSize(20, 20))
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: rgba(255,80,80,0.25); }}"
        )
        close_btn.clicked.connect(self.close)
        h_layout.addWidget(close_btn)
        layout.addWidget(header)

        # Text
        desc = QLabel(self._text)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {c.fg}; font-size: 13px; line-height: 1.5; background: transparent;")
        layout.addWidget(desc)
        
        layout.addStretch()
        
        # OK Button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setFixedSize(100, 36)
        ok_btn.setStyleSheet(
            f"QPushButton {{ background: {c.accent}; color: {c.bg}; border-radius: 6px; font-weight: bold; font-size: 13px; }}"
            f"QPushButton:hover {{ background: rgba({_ar},{_ag},{_ab}, 0.8); }}"
        )
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        outer.addWidget(container)
