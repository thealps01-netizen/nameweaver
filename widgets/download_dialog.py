"""Progress dialog for model downloads (Ollama pull or HF GGUF)."""

from __future__ import annotations

import webbrowser

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from models import LlmModel, is_reupload, is_trusted_source, ollama_tag_candidates
from providers import ProviderState, ProviderStatus
from themes import get_theme
from workers import DownloadWorker


class DownloadDialog(QDialog):
    """Shows live progress for a running DownloadWorker."""

    def __init__(
        self,
        worker: DownloadWorker,
        title: str = "Downloading model",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        self._worker = worker
        self._success = False
        self._message = ""

        layout = QVBoxLayout(self)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._title_label)

        self._status_label = QLabel("Starting…")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        layout.addWidget(self._bar)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._cancel)
        button_row.addWidget(self._cancel_btn)
        self._close_btn = QPushButton("Close")
        self._close_btn.setEnabled(False)
        self._close_btn.clicked.connect(self.accept)
        button_row.addWidget(self._close_btn)
        layout.addLayout(button_row)

        # Wire worker signals
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_error)

    def _on_progress(self, pct: int, msg: str):
        if pct < 0:
            # Indeterminate — keep bar at last known value
            self._bar.setRange(0, 0)  # Busy indicator
        else:
            self._bar.setRange(0, 100)
            self._bar.setValue(pct)
        self._status_label.setText(msg or "Working…")

    def _on_finished(self, ok: bool, message: str):
        self._success = ok
        self._message = message
        self._bar.setRange(0, 100)
        self._bar.setValue(100 if ok else 0)
        self._status_label.setText(f"✔ {message}" if ok else f"✗ {message}")
        self._cancel_btn.setEnabled(False)
        self._close_btn.setEnabled(True)
        self._close_btn.setDefault(True)

    def _on_error(self, err: str):
        self._success = False
        self._message = err
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._status_label.setText(f"Error: {err}")
        self._cancel_btn.setEnabled(False)
        self._close_btn.setEnabled(True)

    def _cancel(self):
        if self._worker.isRunning():
            self._worker.cancel()
            self._status_label.setText("Cancelling…")
            self._cancel_btn.setEnabled(False)

    @property
    def success(self) -> bool:
        return self._success

    @property
    def message(self) -> str:
        return self._message

    def closeEvent(self, event):
        if self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        super().closeEvent(event)


# Human-friendly descriptions for common GGUF quant types.
# Ordered roughly from smallest/lowest quality to largest/highest.
_QUANT_INFO: dict[str, tuple[str, str]] = {
    # quant -> (short label, description)
    "Q2_K": ("Smallest", "Very low quality — for testing only"),
    "Q3_K_S": ("Small", "Low quality, small file"),
    "Q3_K_M": ("Small", "Low-to-medium quality"),
    "Q3_K_L": ("Small+", "Medium quality"),
    "IQ3_XS": ("Small (IQ)", "Smart 3-bit — balanced"),
    "IQ3_S": ("Small (IQ)", "Smart 3-bit"),
    "IQ3_M": ("Small (IQ)", "Smart 3-bit, better"),
    "Q4_0": ("Legacy-4bit", "Legacy 4-bit — prefer modern variants"),
    "Q4_K_S": ("Medium", "4-bit small — speed-focused"),
    "Q4_K_M": ("Recommended", "Quality/size balance — ideal for most uses"),
    "IQ4_XS": ("Medium (IQ)", "Smart 4-bit, smaller"),
    "IQ4_NL": ("Medium (IQ)", "Smart 4-bit, balanced"),
    "Q5_0": ("Legacy-5bit", "Legacy 5-bit"),
    "Q5_K_S": ("High quality", "5-bit small"),
    "Q5_K_M": ("High quality", "High quality — clearly better than Q4"),
    "Q6_K": ("Very high", "Near-FP16 quality, large file"),
    "Q8_0": ("Full quality", "Maximum quality, very large"),
    "F16": ("Raw", "Uncompressed — huge file"),
    "BF16": ("Raw", "Uncompressed — huge file"),
}


def _detect_quant(filename: str) -> str:
    """Extract quant tag (Q4_K_M, IQ3_S, etc.) from a GGUF filename."""
    upper = filename.upper()
    # Longest keys first so Q4_K_M matches before Q4
    for key in sorted(_QUANT_INFO.keys(), key=len, reverse=True):
        if key in upper:
            return key
    return ""


class GgufPickerDialog(QDialog):
    """Lets the user pick a specific GGUF file from a repo tree listing.

    Shows quant type with a plain-English description and file size, and
    highlights the model the scorer recommended as "best_quant" so a user
    who doesn't know what Q4_K_M means can still pick confidently.
    """

    def __init__(
        self,
        repo_id: str,
        files: list[dict],
        parent=None,
        recommended_quant: str = "",
        vram_budget_gb: float = 0.0,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Pick GGUF — {repo_id}")
        self.setMinimumSize(780, 380)

        self._selected: str = ""
        recommended_quant = (recommended_quant or "").upper()

        layout = QVBoxLayout(self)
        hint = (
            f"Found {len(files)} GGUF files in <b>{repo_id}</b>. "
            "<b>Quant</b> is the compression level; the <b>Recommended</b> "
            "row is the best balance for your hardware."
        )
        if vram_budget_gb > 0:
            hint += (
                f"<br><span style='color:#888'>Budget: ~{vram_budget_gb:.1f} GB "
                "(sizes over budget are red, ones that fit are green).</span>"
            )
        header = QLabel(hint)
        header.setWordWrap(True)
        layout.addWidget(header)

        self._table = QTableWidget(len(files), 4)
        self._table.setHorizontalHeaderLabels(["File", "Quant", "Size", "Description"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        # Order: recommended first, then by size ascending
        sorted_files = sorted(files, key=lambda d: d.get("size", 0))
        recommended_row = -1

        self._paths: list[str] = []
        for row, item in enumerate(sorted_files):
            path = item["path"]
            self._paths.append(path)
            size_bytes = item.get("size", 0)
            size_gb = size_bytes / (1024**3)
            quant = _detect_quant(path)
            label, desc = _QUANT_INFO.get(quant, ("", "Unknown format"))

            name_item = QTableWidgetItem(path.split("/")[-1])
            name_item.setToolTip(path)
            self._table.setItem(row, 0, name_item)

            quant_item = QTableWidgetItem(quant or "?")
            quant_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 1, quant_item)

            size_str = (
                f"{size_gb:.2f} GB" if size_gb >= 0.05 else (f"{size_bytes / (1024 * 1024):.0f} MB")
            )
            size_item = QTableWidgetItem(size_str)
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if vram_budget_gb > 0 and size_gb > 0:
                if size_gb <= vram_budget_gb * 0.85:
                    size_item.setForeground(Qt.GlobalColor.green)
                elif size_gb <= vram_budget_gb:
                    size_item.setForeground(Qt.GlobalColor.yellow)
                else:
                    size_item.setForeground(Qt.GlobalColor.red)
            self._table.setItem(row, 2, size_item)

            # Description: mark recommended row
            if quant and quant == recommended_quant and recommended_row < 0:
                desc_text = f"⭐ Recommended · {label} — {desc}"
                recommended_row = row
            elif label:
                desc_text = f"{label} — {desc}"
            else:
                desc_text = desc
            self._table.setItem(row, 3, QTableWidgetItem(desc_text))

        # Fallback: if we didn't find the recommended quant, pick Q4_K_M,
        # then Q5_K_M, then the median size
        if recommended_row < 0:
            for preferred in ("Q4_K_M", "Q5_K_M", "Q4_K_S"):
                for i, path in enumerate(self._paths):
                    if _detect_quant(path) == preferred:
                        recommended_row = i
                        break
                if recommended_row >= 0:
                    break
        if recommended_row < 0 and self._paths:
            recommended_row = len(self._paths) // 2

        if recommended_row >= 0:
            self._table.selectRow(recommended_row)

        self._table.doubleClicked.connect(self._accept)
        layout.addWidget(self._table)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        row = self._table.currentRow()
        if 0 <= row < len(self._paths):
            self._selected = self._paths[row]
            self.accept()

    @property
    def selected_filename(self) -> str:
        return self._selected


def _format_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _short_date(iso: str) -> str:
    """Convert '2024-11-03T12:34:56.000Z' → '2024-11-03'."""
    return iso.split("T", 1)[0] if iso else ""


class GgufMirrorPickerDialog(QDialog):
    """Pick a GGUF mirror repo from search results with match-quality hints.

    Shows repo id, download count, last updated, and a simple match score so
    the user can tell whether ``bartowski/Qwen3-30B-A3B-GGUF`` really matches
    the model they wanted versus ``bartowski/Qwen3-8B-GGUF``.
    """

    def __init__(
        self,
        base_name: str,
        candidates: list[dict],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Pick GGUF mirror — {base_name}")
        self.setMinimumSize(720, 420)
        self._selected_repo: str = ""

        # Tokenize base_name for match scoring. Split on non-alnum, lowercase.
        import re

        self._tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", base_name.lower()) if t]

        layout = QVBoxLayout(self)
        header = QLabel(
            f"Found {len(candidates)} GGUF mirrors for <b>{base_name}</b>.<br>"
            "<span style='color:#888'>Pick one with a high download count and "
            "a high <b>match score</b>. If unsure, use 'Open on HF' to preview "
            "the page.</span>"
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self._table = QTableWidget(len(candidates), 5)
        self._table.setHorizontalHeaderLabels(
            ["Provider", "Repo", "Downloads", "Updated", "Match score"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        # Rank by (match_score desc, downloads desc) and populate
        scored = []
        for c in candidates:
            rid = c.get("id", "")
            score = self._match_score(rid)
            downloads = int(c.get("downloads") or 0)
            last = _short_date(c.get("lastModified") or "")
            scored.append((score, downloads, rid, last))
        scored.sort(key=lambda t: (-t[0], -t[1]))

        self._repo_ids: list[str] = []
        for row, (score, downloads, rid, last) in enumerate(scored):
            self._repo_ids.append(rid)
            provider, _, repo_name = rid.partition("/")
            if not repo_name:
                provider, repo_name = "", rid

            prov_item = QTableWidgetItem(provider)
            prov_item.setToolTip(provider)
            self._table.setItem(row, 0, prov_item)
            repo_item = QTableWidgetItem(repo_name)
            repo_item.setToolTip(rid)
            self._table.setItem(row, 1, repo_item)

            dl = QTableWidgetItem(_format_count(downloads))
            dl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 2, dl)
            self._table.setItem(row, 3, QTableWidgetItem(last))
            pct = round(score * 100)
            m = QTableWidgetItem(f"%{pct}")
            m.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if score >= 0.8:
                m.setForeground(Qt.GlobalColor.green)
            elif score >= 0.5:
                m.setForeground(Qt.GlobalColor.yellow)
            else:
                m.setForeground(Qt.GlobalColor.red)
            self._table.setItem(row, 4, m)

        if scored:
            self._table.selectRow(0)
        self._table.doubleClicked.connect(self._accept)
        layout.addWidget(self._table)

        button_row = QHBoxLayout()
        open_btn = QPushButton("Open on HF")
        open_btn.clicked.connect(self._open_in_browser)
        button_row.addWidget(open_btn)
        button_row.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)

    def _match_score(self, repo_id: str) -> float:
        if not self._tokens:
            return 0.0
        # Strip org prefix, match on repo name body
        body = repo_id.split("/", 1)[-1].lower()
        hits = sum(1 for t in self._tokens if t in body)
        return hits / len(self._tokens)

    def _current_repo(self) -> str:
        row = self._table.currentRow()
        if 0 <= row < len(self._repo_ids):
            return self._repo_ids[row]
        return ""

    def _open_in_browser(self):
        rid = self._current_repo()
        if rid:
            webbrowser.open(f"https://huggingface.co/{rid}")

    def _accept(self):
        self._selected_repo = self._current_repo()
        if self._selected_repo:
            self.accept()

    @property
    def selected_repo(self) -> str:
        return self._selected_repo


class DownloadSourceDialog(QDialog):
    """Where to download from, and as what — one dialog, not a chain of them.

    The old flow asked four questions in sequence: a trust warning, a source list,
    an "Ollama is off" confirmation, then the tag. Each answer was given before
    the next question was visible, and two of them were modal interruptions. Here
    the source, its id field and the trust warning are on one screen: an
    unverified publisher needs its checkbox ticked, and the id field belongs to
    the source that has one (Ollama's tag), prefilled with the likely library
    name but editable.
    """

    def __init__(
        self,
        model: LlmModel,
        providers: list[ProviderStatus],
        theme_name: str = "dark",
        parent=None,
    ):
        super().__init__(parent)
        self._model = model
        self._providers = list(providers)
        self._theme = get_theme(theme_name)

        self.setWindowTitle(f"Download {model.name}")
        self.setMinimumWidth(540)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel(model.name)
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        title.setWordWrap(True)
        layout.addWidget(title)

        subtitle = " · ".join(
            part
            for part in (model.provider, model.parameter_count, (model.format or "").upper())
            if part
        )
        if subtitle:
            sub = QLabel(subtitle)
            sub.setStyleSheet(f"color: {self._theme.fg_muted}; font-size: 11px;")
            layout.addWidget(sub)

        self._check: QCheckBox | None = None
        if not is_trusted_source(model):
            layout.addWidget(self._build_warning())

        layout.addWidget(self._build_sources())

        # Ollama's id, in its own row so the other sources do not carry it.
        self._tag_row = QWidget()
        tag_layout = QHBoxLayout(self._tag_row)
        tag_layout.setContentsMargins(0, 0, 0, 0)
        tag_layout.setSpacing(8)
        tag_label = QLabel("Ollama tag")
        tag_label.setStyleSheet(f"color: {self._theme.fg_muted}; font-size: 11px;")
        tag_layout.addWidget(tag_label)
        self._tag_combo = QComboBox()
        self._tag_combo.setEditable(True)
        self._tag_combo.addItems(ollama_tag_candidates(model.name))
        self._tag_combo.setToolTip(
            "The exact tag `ollama pull` receives. Ollama's library names differ from "
            "HuggingFace ones — edit it if the guess is wrong."
        )
        self._tag_combo.currentTextChanged.connect(lambda _t: self._sync())
        tag_layout.addWidget(self._tag_combo, stretch=1)
        layout.addWidget(self._tag_row)

        self._detail = QLabel("")
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet(f"color: {self._theme.fg_muted}; font-size: 11px;")
        layout.addWidget(self._detail)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self._cancel_btn)
        self._download_btn = QPushButton("Download")
        self._download_btn.setDefault(True)
        self._download_btn.setStyleSheet(
            f"QPushButton {{ background: {self._theme.accent};"
            f" color: {self._theme.accent_text}; border: none; border-radius: 6px;"
            f" padding: 6px 16px; font-weight: 600; }}"
            f" QPushButton:hover {{ background: {self._theme.accent_hover}; }}"
            f" QPushButton:disabled {{ background: {self._theme.bg_alt};"
            f" color: {self._theme.fg_muted}; }}"
        )
        self._download_btn.clicked.connect(self.accept)
        buttons.addWidget(self._download_btn)
        layout.addLayout(buttons)

        # Only now: checking a radio calls _sync, which reads every widget above.
        if self._radios:
            next(iter(self._radios.values())).setChecked(True)
        self._sync()

    # ------------------------------------------------------------------ build

    def _build_warning(self) -> QWidget:
        """The unverified-source warning, inline, gating the Download button."""
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        text = (
            f"'{self._model.provider}' is not a recognised first-party publisher — "
            "you would be downloading and running model files from this source."
        )
        if is_reupload(self._model):
            text += f"\nThis looks like a community re-upload of: {self._model.base_model}"
        warning = QLabel(text)
        warning.setWordWrap(True)
        warning.setStyleSheet(f"color: {self._theme.warning}; font-size: 11px;")
        layout.addWidget(warning)

        self._check = QCheckBox("I understand and want to continue")
        self._check.setStyleSheet(f"color: {self._theme.fg}; font-size: 11px;")
        self._check.toggled.connect(lambda _c: self._sync())
        layout.addWidget(self._check)

        box.setStyleSheet(
            f"QWidget {{ background: {self._theme.bg_alt};"
            f" border: 1px solid {self._theme.warning}; border-radius: 8px; }}"
        )
        return box

    def _build_sources(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label = QLabel("Download from")
        label.setStyleSheet(f"color: {self._theme.fg_muted}; font-size: 11px;")
        layout.addWidget(label)

        self._radios: dict[str, QRadioButton] = {}
        for key in self.available_sources():
            radio = QRadioButton(self._source_label(key))
            radio.setStyleSheet(f"color: {self._theme.fg}; font-size: 12px;")
            radio.toggled.connect(lambda checked, k=key: self._sync() if checked else None)
            layout.addWidget(radio)
            self._radios[key] = radio
        return box

    # ------------------------------------------------------------------ state

    def _engine_state(self, key: str) -> ProviderState:
        wanted = {"ollama": "ollama", "lmstudio": "lm studio"}[key]
        for provider in self._providers:
            if provider.name.lower() == wanted:
                return provider.state
        return ProviderState.NOT_INSTALLED

    def available_sources(self) -> list[str]:
        """Engine choices that exist on this machine, ready ones first, then HF."""
        offered = [
            key
            for key in ("ollama", "lmstudio")
            if self._engine_state(key) != ProviderState.NOT_INSTALLED
        ]
        offered.sort(key=lambda key: 0 if self._engine_state(key) == ProviderState.READY else 1)
        return offered + ["hf"]

    def _source_label(self, key: str) -> str:
        if key == "hf":
            return "HuggingFace GGUF (choose repo and file next)"
        name = {"ollama": "Ollama", "lmstudio": "LM Studio"}[key]
        state = self._engine_state(key)
        if state == ProviderState.READY:
            return f"{name}  ·  ready"
        return f"{name}  ·  off — will be started first"

    def selected_source(self) -> str:
        for key, radio in self._radios.items():
            if radio.isChecked():
                return key
        return self.available_sources()[0]

    def selected_id(self) -> str:
        """The id this download is asked for: Ollama's tag, empty otherwise."""
        if self.selected_source() != "ollama":
            return ""
        return self._tag_combo.currentText().strip()

    def wants_engine_start(self) -> bool:
        """True when the chosen engine is installed but not running."""
        key = self.selected_source()
        if key == "hf":
            return False
        return self._engine_state(key) == ProviderState.INSTALLED_OFF

    def _hint(self, key: str) -> str:
        if key == "ollama":
            return (
                "Pulled into Ollama's own store and listed on My Models. Its library may "
                "not have this model — a failed pull offers the GGUF paths instead."
            )
        if key == "lmstudio":
            return (
                "Written into LM Studio's models folder as GGUF; LM Studio picks it up "
                "without a restart. The repo and file are chosen next."
            )
        return (
            "A GGUF file from any repo, into a folder you choose. "
            "The repo and file are chosen next."
        )

    def _sync(self) -> None:
        """Everything the current answer changes: the id field, the hint, Download."""
        source = self.selected_source()
        self._tag_row.setVisible(source == "ollama")
        self._detail.setText(self._hint(source))

        enabled = self._check is None or self._check.isChecked()
        if source == "ollama" and not self.selected_id():
            enabled = False
        self._download_btn.setEnabled(enabled)
