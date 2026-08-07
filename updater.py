"""updater.py — Auto-update via GitHub Releases.

Checks the latest release tag on GitHub in a background QThread.
If a newer version exists, emits `update_available(version, download_url)`.

Usage in nameweaver.py:
    from updater import UpdateChecker, prompt_and_install
    checker = UpdateChecker("thealps01-netizen", "nameweaver")   # ← GitHub user/repo
    checker.update_available.connect(on_update)
    checker.start()

GitHub Release convention:
    Tag:   v1.2.3
    Asset: Nameweaver_Setup.exe   (the installer)
"""

import re
import os
import sys
import ssl
import hashlib
import tempfile
import urllib.request
import urllib.error
import json

from PyQt6.QtCore    import QThread, pyqtSignal, QObject, Qt, QPoint, QRectF
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QApplication, QFrame, QWidget,
)
from PyQt6.QtGui     import QFont, QPainter, QColor, QPainterPath

from version import __version__
from logger  import get_logger

_log = get_logger("updater")

# Keeps downloader + progress dialog alive until download finishes (prevents GC)
_active: list = []

# ── Version comparison ─────────────────────────────────────────────────────────

def _parse(tag: str) -> tuple[int, ...]:
    """'v1.2.3' → (1, 2, 3)"""
    nums = re.findall(r"\d+", tag)
    return tuple(int(n) for n in nums)


def _is_newer(remote_tag: str, current: str = __version__) -> bool:
    return _parse(remote_tag) > _parse(current)


# ── GitHub API fetch ───────────────────────────────────────────────────────────

GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
TIMEOUT    = 8   # seconds


def _fetch_latest(owner: str, repo: str) -> dict | None:
    url = GITHUB_API.format(owner=owner, repo=repo)
    req = urllib.request.Request(
        url,
        headers={
            "Accept":     "application/vnd.github+json",
            "User-Agent": f"Nameweaver-Updater/{__version__}",
        },
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        _log.warning("GitHub API HTTP %s for %s/%s", e.code, owner, repo)
    except urllib.error.URLError as e:
        _log.debug("Update check skipped (no network?): %s", e.reason)
    except Exception as e:
        _log.error("Update check error: %s", e)
    return None


def _find_installer_asset(release: dict) -> str | None:
    """Return download URL of the first .exe asset, or None."""
    for asset in release.get("assets", []):
        if asset.get("name", "").lower().endswith(".exe"):
            return asset["browser_download_url"]
    return None


# ── Background checker ─────────────────────────────────────────────────────────

class UpdateChecker(QObject):
    """Runs a single version check on a background QThread.

    Signals:
        update_available(str tag, str download_url, str release_notes)
        no_update()
        check_failed()
    """

    update_available = pyqtSignal(str, str, str)  # (tag, download_url, notes)
    no_update        = pyqtSignal()
    check_failed     = pyqtSignal()

    def __init__(self, owner: str, repo: str, parent=None):
        super().__init__()
        self._owner = owner
        self._repo  = repo
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)

    def start(self) -> None:
        """Start the background check (non-blocking)."""
        self._thread.start()

    def _run(self) -> None:
        _log.debug("Checking for updates (%s/%s, current=%s)",
                   self._owner, self._repo, __version__)

        # Import here to avoid circular imports at module load time
        from cfg import load_cfg
        skipped = load_cfg().get("skipped_version", "")

        release = _fetch_latest(self._owner, self._repo)
        if release is None:
            self.check_failed.emit()
        else:
            tag = release.get("tag_name", "")
            if tag and tag == skipped:
                _log.debug("Version %s skipped by user.", tag)
                self.no_update.emit()
            elif _is_newer(tag):
                url   = _find_installer_asset(release)
                notes = release.get("body", "") or ""
                if url:
                    _log.info("Update available: %s (asset: %s)", tag, url)
                    self.update_available.emit(tag, url, notes)
                else:
                    _log.info("Update %s found but no .exe asset attached.", tag)
                    self.no_update.emit()
            else:
                _log.debug("Already up to date (%s).", __version__)
                self.no_update.emit()
        self._thread.quit()


# ── Download + launch installer ────────────────────────────────────────────────

class InstallerDownloader(QObject):
    """Downloads the installer to a temp file then runs it."""

    progress = pyqtSignal(int)    # 0-100
    finished = pyqtSignal(str)    # path to downloaded installer
    error    = pyqtSignal(str)

    def __init__(self, url: str, parent=None):
        super().__init__()
        self._url    = url
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            suffix  = os.path.basename(self._url.split("?")[0]) or "Nameweaver_Setup.exe"
            tmp_dir = tempfile.mkdtemp(prefix="nameweaver_update_")
            dest    = os.path.join(tmp_dir, suffix)
            _log.info("Downloading update from %s → %s", self._url, dest)

            def _reporthook(block, block_size, total):
                if total > 0:
                    pct = min(int(block * block_size * 100 / total), 100)
                    self.progress.emit(pct)

            urllib.request.urlretrieve(self._url, dest, reporthook=_reporthook)
            self.progress.emit(100)
            _log.info("Download complete: %s", dest)

            # SHA256 integrity check — download .sha256 sidecar if available
            sha256_url = self._url + ".sha256"
            try:
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(
                    urllib.request.Request(sha256_url, headers={"User-Agent": "Nameweaver-Updater/1.0"}),
                    timeout=TIMEOUT,
                    context=ctx,
                ) as r:
                    expected_hash = r.read().decode().split()[0].strip().lower()
                with open(dest, "rb") as _f:
                    actual_hash = hashlib.sha256(_f.read()).hexdigest()
                if actual_hash != expected_hash:
                    raise ValueError(f"SHA256 mismatch: expected {expected_hash}, got {actual_hash}")
                _log.info("SHA256 verified OK: %s", actual_hash)
            except urllib.error.URLError:
                _log.warning("No .sha256 sidecar found — installer integrity not verified")

            self.finished.emit(dest)
        except Exception as e:
            _log.error("Download failed: %s", e)
            self.error.emit(str(e))
        finally:
            self._thread.quit()


# ── Reusable UI helpers ────────────────────────────────────────────────────────

class _Panel(QWidget):
    """Opaque rounded dark panel — reliable background on WA_TranslucentBackground."""
    BG     = QColor("#141420")
    BORDER = QColor("#2a2a45")
    RADIUS = 10.0

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        p.fillPath(path, self.BG)
        p.setPen(self.BORDER)
        p.drawPath(path)
        p.end()


class _DraggableDialog(QDialog):
    """Frameless dialog that can be dragged by clicking anywhere."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_pos: QPoint | None = None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _e):
        self._drag_pos = None

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.x() + (screen.width()  - self.width())  // 2,
            screen.y() + (screen.height() - self.height()) // 2,
        )


# ── Modern update dialog ───────────────────────────────────────────────────────

_STYLE = """
QDialog {
    background: transparent;
}
QLabel#title {
    color: #ffffff;
    font-size: 16px;
    font-weight: bold;
}
QLabel#subtitle {
    color: #8888aa;
    font-size: 11px;
}
QLabel#version_current {
    color: #8888aa;
    font-size: 13px;
}
QLabel#version_new {
    color: #00d4ff;
    font-size: 13px;
    font-weight: bold;
}
QLabel#notes_label {
    color: #aaaacc;
    font-size: 11px;
}
QFrame#separator {
    color: #2a2a45;
}
QPushButton#btn_update {
    background-color: #00d4ff;
    color: #0a0a14;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton#btn_update:hover {
    background-color: #33ddff;
}
QPushButton#btn_later {
    background-color: #1e1e35;
    color: #aaaacc;
    border: 1px solid #2a2a45;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 12px;
}
QPushButton#btn_later:hover {
    background-color: #28283f;
    color: #ccccee;
}
QPushButton#btn_skip {
    background-color: transparent;
    color: #555577;
    border: none;
    padding: 8px 12px;
    font-size: 11px;
}
QPushButton#btn_skip:hover {
    color: #8888aa;
}
QProgressBar {
    background-color: #1e1e35;
    border: 1px solid #2a2a45;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background-color: #00d4ff;
    border-radius: 4px;
}
"""


class UpdateDialog(_DraggableDialog):
    """Modern dark-themed update dialog."""

    # result codes
    SKIP  = 2
    UPDATE = 1
    LATER  = 0

    def __init__(self, tag: str, notes: str, parent=None):
        super().__init__(parent)
        self._tag   = tag
        self._choice = self.LATER

        self.setWindowTitle("Nameweaver — Update Available")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(400)
        self.setStyleSheet(_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        container = _Panel(self)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(24, 24, 24, 20)
        inner.setSpacing(14)
        root.addWidget(container)

        # ── Header ────────────────────────────────────────────────────────────
        title = QLabel("New Update")
        title.setObjectName("title")
        subtitle = QLabel("An update is available for Nameweaver.")
        subtitle.setObjectName("subtitle")
        inner.addWidget(title)
        inner.addWidget(subtitle)

        # ── Separator ─────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        inner.addWidget(sep)

        # ── Version row ───────────────────────────────────────────────────────
        ver_row = QHBoxLayout()
        ver_row.setSpacing(6)

        cur_lbl = QLabel("Current:")
        cur_lbl.setObjectName("version_current")
        cur_ver = QLabel(__version__)
        cur_ver.setObjectName("version_current")

        arrow = QLabel("→")
        arrow.setObjectName("subtitle")

        new_lbl = QLabel("New:")
        new_lbl.setObjectName("version_current")
        new_ver = QLabel(tag)
        new_ver.setObjectName("version_new")

        ver_row.addWidget(cur_lbl)
        ver_row.addWidget(cur_ver)
        ver_row.addWidget(arrow)
        ver_row.addWidget(new_lbl)
        ver_row.addWidget(new_ver)
        ver_row.addStretch()
        inner.addLayout(ver_row)

        # ── Release notes (trimmed) ────────────────────────────────────────────
        if notes and notes.strip():
            notes_lbl = QLabel(notes.strip()[:320] + ("…" if len(notes.strip()) > 320 else ""))
            notes_lbl.setObjectName("notes_label")
            notes_lbl.setWordWrap(True)
            inner.addWidget(notes_lbl)

        # ── Separator ─────────────────────────────────────────────────────────
        sep2 = QFrame()
        sep2.setObjectName("separator")
        sep2.setFrameShape(QFrame.Shape.HLine)
        inner.addWidget(sep2)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._btn_skip = QPushButton("Skip This Version")
        self._btn_skip.setObjectName("btn_skip")
        self._btn_skip.clicked.connect(self._on_skip)

        btn_row.addWidget(self._btn_skip)
        btn_row.addStretch()

        self._btn_later = QPushButton("Later")
        self._btn_later.setObjectName("btn_later")
        self._btn_later.clicked.connect(self.reject)

        self._btn_update = QPushButton("Update")
        self._btn_update.setObjectName("btn_update")
        self._btn_update.setDefault(True)
        self._btn_update.clicked.connect(self._on_update)

        btn_row.addWidget(self._btn_later)
        btn_row.addWidget(self._btn_update)
        inner.addLayout(btn_row)

    def _on_update(self):
        self._choice = self.UPDATE
        self.accept()

    def _on_skip(self):
        self._choice = self.SKIP
        self.accept()

    def choice(self) -> int:
        return self._choice


class DownloadProgressDialog(_DraggableDialog):
    """Minimal dark progress dialog for installer download."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nameweaver — Downloading")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(360, 120)
        self.setStyleSheet(_STYLE)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        container = _Panel(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        root.addWidget(container)

        lbl = QLabel("Downloading update…")
        lbl.setObjectName("title")
        lbl.setFont(QFont(lbl.font().family(), 13))
        layout.addWidget(lbl)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedHeight(8)
        layout.addWidget(self._bar)

        self._pct_lbl = QLabel("0%")
        self._pct_lbl.setObjectName("subtitle")
        self._pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._pct_lbl)

    def set_progress(self, pct: int) -> None:
        self._bar.setValue(pct)
        self._pct_lbl.setText(f"{pct}%")
        QApplication.processEvents()

    def set_installing(self) -> None:
        self.setWindowTitle("Nameweaver — Installing")
        for child in self.findChildren(QLabel):
            if child.objectName() == "title":
                child.setText("Installing update…")
                break
        self._bar.setRange(0, 0)
        self._pct_lbl.setText("please wait")
        QApplication.processEvents()


# ── Download error dialog ─────────────────────────────────────────────────────

def _friendly_error(raw: str) -> tuple[str, str]:
    """Return (title, body) user-friendly message from a raw exception string."""
    r = raw.lower()
    if "getaddrinfo" in r or "name or service not known" in r or "nodename nor servname" in r:
        return (
            "No Internet Connection",
            "Could not reach the update server.\n"
            "Please check your internet connection and try again.",
        )
    if "timed out" in r or "timeout" in r:
        return (
            "Connection Timed Out",
            "The update server took too long to respond.\n"
            "Please try again in a moment.",
        )
    if "connection refused" in r:
        return (
            "Connection Refused",
            "The update server refused the connection.\n"
            "Please try again later.",
        )
    if "ssl" in r or "certificate" in r:
        return (
            "Secure Connection Failed",
            "Could not establish a secure connection to the server.\n"
            "Please check your system date/time and try again.",
        )
    return (
        "Download Failed",
        "An error occurred while downloading the update.\n"
        "Please try again later.",
    )


class _ErrorDialog(_DraggableDialog):
    """Styled error dialog matching the Nameweaver dark theme."""

    def __init__(self, title: str, body: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nameweaver — Update Error")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(380)
        self.setStyleSheet(_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        container = _Panel(self)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(24, 22, 24, 20)
        inner.setSpacing(14)
        root.addWidget(container)

        # ── Header row ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        icon_lbl = QLabel("⚠")
        icon_lbl.setStyleSheet("color:#ff5555; font-size:20px; background:transparent;")
        title_lbl = QLabel(title)
        title_lbl.setObjectName("title")
        title_lbl.setWordWrap(True)
        hdr.addWidget(icon_lbl)
        hdr.addWidget(title_lbl, 1)
        inner.addLayout(hdr)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.Shape.HLine)
        inner.addWidget(sep)

        # ── Body text ─────────────────────────────────────────────────────────
        body_lbl = QLabel(body)
        body_lbl.setObjectName("subtitle")
        body_lbl.setWordWrap(True)
        body_lbl.setStyleSheet("color:#aaaacc; font-size:12px;")
        inner.addWidget(body_lbl)

        # ── OK button ─────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton("  OK  ")
        btn_ok.setObjectName("btn_later")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)
        inner.addLayout(btn_row)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            self.accept()
        else:
            super().keyPressEvent(e)


def _show_download_error(raw: str, parent=None) -> None:
    title, body = _friendly_error(raw)
    _log.warning("Download error shown to user: %s | raw: %s", title, raw)
    dlg = _ErrorDialog(title, body, parent)
    dlg.adjustSize()
    dlg._center_on_screen()
    dlg.exec()


# ── High-level helper called from main UI ──────────────────────────────────────

def prompt_and_install(tag: str, download_url: str, notes: str = "", parent=None) -> None:
    """Show modern update dialog, then download & run installer if accepted."""
    from cfg import load_cfg, save_cfg

    dlg = UpdateDialog(tag, notes, parent)
    dlg.adjustSize()
    dlg._center_on_screen()
    dlg.exec()

    choice = dlg.choice()

    if choice == UpdateDialog.SKIP:
        cfg = load_cfg()
        cfg["skipped_version"] = tag
        save_cfg(cfg)
        _log.info("Version %s marked as skipped.", tag)
        return

    if choice != UpdateDialog.UPDATE:
        return

    # ── Download phase ────────────────────────────────────────────────────────
    prog = DownloadProgressDialog(parent)
    prog.adjustSize()
    prog._center_on_screen()
    prog.show()

    downloader = InstallerDownloader(download_url)
    _active.extend([downloader, prog])   # prevent GC while thread runs

    def _on_progress(pct: int):
        prog.set_progress(pct)

    def _on_finished(path: str):
        _active.clear()
        prog.set_installing()
        _log.info("Launching installer: %s", path)
        import ctypes

        # ShellExecuteExW — proper struct-based API, avoids return-type truncation
        # issues that plagued ShellExecuteW on 64-bit, and reliably passes args.
        class _SEI(ctypes.Structure):
            _fields_ = [
                ("cbSize",         ctypes.c_uint32),
                ("fMask",          ctypes.c_uint32),
                ("hwnd",           ctypes.c_void_p),
                ("lpVerb",         ctypes.c_wchar_p),
                ("lpFile",         ctypes.c_wchar_p),
                ("lpParameters",   ctypes.c_wchar_p),
                ("lpDirectory",    ctypes.c_wchar_p),
                ("nShow",          ctypes.c_int),
                ("hInstApp",       ctypes.c_void_p),
                ("lpIDList",       ctypes.c_void_p),
                ("lpClass",        ctypes.c_wchar_p),
                ("hkeyClass",      ctypes.c_void_p),
                ("dwHotKey",       ctypes.c_uint32),
                ("hIconOrMonitor", ctypes.c_void_p),
                ("hProcess",       ctypes.c_void_p),
            ]

        sei = _SEI()
        sei.cbSize       = ctypes.sizeof(_SEI)
        sei.lpVerb       = "runas"
        sei.lpFile       = path
        sei.lpParameters = "/VERYSILENT /NORESTART"
        sei.lpDirectory  = os.path.dirname(path)
        sei.nShow        = 1  # SW_SHOWNORMAL (so UAC dialog is visible)

        shell32 = ctypes.windll.shell32
        shell32.ShellExecuteExW.restype = ctypes.c_bool
        ok = shell32.ShellExecuteExW(ctypes.byref(sei))
        if ok:
            _log.info("Installer launched via ShellExecuteExW")
        else:
            err = ctypes.windll.kernel32.GetLastError()
            _log.error("ShellExecuteExW failed (err=%d) — installer not launched", err)

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, parent._quit if parent and hasattr(parent, '_quit') else QApplication.instance().quit)

    def _on_error(msg_text: str):
        _active.clear()
        prog.close()
        _show_download_error(msg_text, parent)

    downloader.progress.connect(_on_progress)
    downloader.finished.connect(_on_finished)
    downloader.error.connect(_on_error)
    downloader.start()
