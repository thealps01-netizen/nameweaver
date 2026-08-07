"""crash_handler.py — Global unhandled exception handler for Nameweaver.

Intercepts uncaught exceptions, writes a timestamped crash log under
%LOCALAPPDATA%/Nameweaver/logs/, and shows a user-friendly dialog with
options to open the log folder or copy the traceback to clipboard.
"""

import sys
import os
import traceback
import datetime

from logger import LOG_DIR, get_logger

_log = get_logger("crash_handler")


def _write_crash_log(exc_type, exc_value, exc_tb) -> tuple[str, str]:
    """Write crash details to a timestamped file. Returns (path, traceback)."""
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOG_DIR, f"crash_{ts}.log")
    tb   = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Nameweaver crash report — {datetime.datetime.now()}\n")
            f.write("=" * 60 + "\n\n")
            f.write(tb)
    except Exception:
        pass
    return path, tb


def _show_crash_dialog(crash_path: str, tb_text: str) -> None:
    """Show a Qt dialog if QApplication is running, otherwise print."""
    try:
        from PyQt6.QtWidgets import QMessageBox, QApplication
        app = QApplication.instance()
        if app is None:
            return

        msg = QMessageBox()
        msg.setWindowTitle("Nameweaver — Beklenmedik Hata")
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText(
            "Uygulama beklenmedik bir hatayla karşılaştı.\n\n"
            f"Crash log kaydedildi:\n{crash_path}"
        )
        msg.setDetailedText(tb_text)

        open_btn = msg.addButton("Log Klasörünü Aç", QMessageBox.ButtonRole.ActionRole)
        copy_btn = msg.addButton("Kopyala",          QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Kapat",                        QMessageBox.ButtonRole.RejectRole)

        msg.exec()

        if msg.clickedButton() == open_btn:
            os.startfile(LOG_DIR)
        elif msg.clickedButton() == copy_btn:
            QApplication.clipboard().setText(tb_text)
    except Exception:
        pass


def install() -> None:
    """Replace sys.excepthook with Nameweaver's crash handler."""

    def _handler(exc_type, exc_value, exc_tb):
        # Let KeyboardInterrupt through normally
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _log.critical("Unhandled exception:\n%s", tb_str)

        crash_path, tb_text = _write_crash_log(exc_type, exc_value, exc_tb)
        _show_crash_dialog(crash_path, tb_text)

    sys.excepthook = _handler
    _log.debug("Crash handler installed.")
