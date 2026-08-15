"""Main model table — QAbstractTableModel + QSortFilterProxyModel + QTableView."""

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    pyqtSignal,
)
import qtawesome as qta
from PyQt6.QtGui import QAction, QColor, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QMenu,
    QTableView,
)

from models import (
    SUPPORTED_FORMATS,
    is_engine_compatible,
    is_reupload,
    is_trusted_source,
    size_class,
)
from scoring import FitLevel, ModelFit, RunMode, pc_comfort
from themes import ThemeColors, get_theme

COLUMNS = [
    ("", "check"),              # 0 — checkbox only
    ("Model Name", "name"),
    ("Provider", "provider"),
    ("Parameters", "params"),
    ("Size", "size"),
    ("Overall Score", "score"),
    ("Est. TPS", "tps"),
    ("PC Load", "comfort"),
    ("Quantization", "quant"),
    ("Disk Size", "disk"),
    ("Run Type", "run_mode"),
    ("RAM Usage", "mem_pct"),
    ("Context Length", "ctx"),
    ("Fit Quality", "fit"),
]

# Size class → colour ramp key (small = calm, huge = hot).
_SIZE_ORDER = {"unknown": 0, "tiny": 1, "small": 2, "medium": 3,
               "large": 4, "xl": 5, "huge": 6}
# PC-comfort → sortable rank (easier = higher, so sorting surfaces easy ones).
_COMFORT_ORDER = {"effortless": 5, "comfortable": 4, "demanding": 3,
                  "heavy": 2, "too_much": 1}


class ModelTableModel(QAbstractTableModel):
    """Custom table model backed by list[ModelFit]."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fits: list[ModelFit] = []
        self._theme: ThemeColors = get_theme("dark")
        self._checked: list[int] = []
        self._icon_cache: dict[tuple[str, str], QIcon] = {}

    def set_theme(self, theme_name: str):
        self._theme = get_theme(theme_name)
        self._icon_cache.clear()  # colours changed — rebuild icons on next paint
        top_left = self.index(0, 0)
        bottom_right = self.index(self.rowCount() - 1, self.columnCount() - 1)
        if top_left.isValid() and bottom_right.isValid():
            self.dataChanged.emit(top_left, bottom_right)

    def set_data(self, fits: list[ModelFit]):
        # Preserve checked state by matching model names
        old_checked_names = [self._fits[r].model.name for r in self._checked if r < len(self._fits)]
        self.beginResetModel()
        self._fits = fits
        if old_checked_names:
            # Reconstruct checked list preserving order
            new_checked = []
            for name in old_checked_names:
                for i, f in enumerate(fits):
                    if f.model.name == name and i not in new_checked:
                        new_checked.append(i)
                        break
            self._checked = new_checked
        else:
            self._checked.clear()
        self.endResetModel()

    def checked_fits(self) -> list[ModelFit]:
        """Return fits that are checked for comparison."""
        return [self._fits[r] for r in self._checked if r < len(self._fits)]

    def get_fit(self, row: int) -> ModelFit | None:
        if 0 <= row < len(self._fits):
            return self._fits[row]
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._fits)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section][0]
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.isValid() and index.column() == 0:
            base |= Qt.ItemFlag.ItemIsUserCheckable
        return base

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        fit = self._fits[index.row()]
        col_key = COLUMNS[index.column()][1]

        if col_key == "check":
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if index.row() in self._checked else Qt.CheckState.Unchecked
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_data(fit, col_key)
        elif role == Qt.ItemDataRole.DecorationRole:
            return self._decoration(fit, col_key)
        elif role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground_color(fit, col_key)
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col_key == "check":
                return Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            if col_key in ("params", "score", "tps", "disk", "mem_pct", "ctx"):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        elif role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(fit, col_key)
        elif role == Qt.ItemDataRole.UserRole:
            # Raw sortable value
            return self._sort_value(fit, col_key)

        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            row = index.row()
            checked = value in (Qt.CheckState.Checked, 2)
            if checked:
                if row not in self._checked:
                    if len(self._checked) >= 3:
                        # Remove truly the oldest checked item to keep max 3
                        oldest_row = self._checked.pop(0)
                        old_idx = self.index(oldest_row, 0)
                        self.dataChanged.emit(old_idx, old_idx, [Qt.ItemDataRole.CheckStateRole])
                    self._checked.append(row)
            else:
                if row in self._checked:
                    self._checked.remove(row)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            return True
        return super().setData(index, value, role)

    def _icon(self, name: str, color: str) -> QIcon:
        key = (name, color)
        icon = self._icon_cache.get(key)
        if icon is None:
            icon = qta.icon(name, color=color)
            self._icon_cache[key] = icon
        return icon

    def _decoration(self, fit: ModelFit, col: str) -> QIcon | None:
        """Modern status badges: publisher trust (Provider) + engine fit (Name)."""
        c = self._theme
        if col == "name":
            if not is_engine_compatible(fit.model.format):
                return self._icon("mdi6.engine-off-outline", c.error)
        elif col == "provider":
            if is_trusted_source(fit.model):
                # Verified-badge look, green.
                return self._icon("mdi6.check-decagram", c.good)
            # Distinct shape + colour (red alert-badge) so the two never blur.
            return self._icon("mdi6.alert-decagram-outline", c.error)
        return None

    def _display_data(self, fit: ModelFit, col: str) -> str:
        if col == "name":
            return fit.model.name
        elif col == "provider":
            return fit.model.provider
        elif col == "params":
            p = fit.model.params_b()
            return f"{p:.1f} B" if p >= 1 else f"{p * 1000:.0f} M"
        elif col == "size":
            return size_class(fit.model.params_b())[0]
        elif col == "comfort":
            return pc_comfort(fit)[0]
        elif col == "score":
            return f"{fit.score:.1f} / 100"
        elif col == "tps":
            return f"{fit.estimated_tps:.1f} tok/s"
        elif col == "quant":
            return fit.best_quant
        elif col == "disk":
            d = fit.model.estimate_disk_gb(fit.best_quant)
            return f"{d:.1f} GB"
        elif col == "run_mode":
            return fit.run_mode.value
        elif col == "mem_pct":
            # Add required memory to make it more descriptive
            return f"{fit.memory_required_gb:.1f} GB ({fit.utilization_pct:.0f}%)"
        elif col == "ctx":
            ctx = fit.model.ctx_length
            if ctx >= 1_000_000:
                return f"{ctx / 1_000_000:.1f}M tokens"
            elif ctx >= 1000:
                return f"{ctx // 1000}K tokens"
            return f"{ctx} tokens"
        elif col == "fit":
            return fit.fit_level.value
        return ""

    def _foreground_color(self, fit: ModelFit, col: str) -> QColor | None:
        c = self._theme

        # Dim the whole row when no installed engine can run this format —
        # takes precedence over the per-column colours below.
        if not is_engine_compatible(fit.model.format):
            return QColor(c.fg_muted)

        if col == "fit":
            color_map = {
                FitLevel.PERFECT: c.fit_perfect,
                FitLevel.GOOD: c.fit_good,
                FitLevel.MARGINAL: c.fit_marginal,
                FitLevel.TOO_TIGHT: c.fit_tight,
            }
            return QColor(color_map.get(fit.fit_level, c.fg))

        if col == "run_mode":
            color_map = {
                RunMode.GPU: c.mode_gpu,
                RunMode.MOE_OFFLOAD: c.mode_moe,
                RunMode.CPU_OFFLOAD: c.mode_offload,
                RunMode.CPU_ONLY: c.mode_cpu,
                RunMode.TENSOR_PARALLEL: c.mode_gpu,
            }
            return QColor(color_map.get(fit.run_mode, c.fg))

        if col == "score":
            if fit.score >= 75:
                return QColor(c.score_high)
            elif fit.score >= 50:
                return QColor(c.score_mid)
            else:
                return QColor(c.score_low)

        if col == "size":
            key = size_class(fit.model.params_b())[1]
            ramp = {
                "tiny": c.good, "small": c.good, "medium": c.fg,
                "large": c.warning, "xl": c.error, "huge": c.error,
            }
            return QColor(ramp.get(key, c.fg_muted))

        if col == "comfort":
            key = pc_comfort(fit)[1]
            cmap = {
                "effortless": c.good, "comfortable": c.good,
                "demanding": c.warning, "heavy": c.warning, "too_much": c.error,
            }
            return QColor(cmap.get(key, c.fg))

        return None

    def _sort_value(self, fit: ModelFit, col: str):
        if col == "name":
            return fit.model.name.lower()
        elif col == "provider":
            return fit.model.provider.lower()
        elif col == "params":
            return fit.model.params_b()
        elif col == "size":
            return fit.model.params_b()
        elif col == "comfort":
            return _COMFORT_ORDER.get(pc_comfort(fit)[1], 0)
        elif col == "score":
            return fit.score
        elif col == "tps":
            return fit.estimated_tps
        elif col == "quant":
            return fit.best_quant
        elif col == "disk":
            return fit.model.estimate_disk_gb(fit.best_quant)
        elif col == "run_mode":
            return fit.run_mode.value
        elif col == "mem_pct":
            return fit.utilization_pct
        elif col == "ctx":
            return fit.model.ctx_length
        elif col == "fit":
            return fit.fit_level.rank
        return ""

    def _tooltip(self, fit: ModelFit, col: str) -> str:
        if col == "name":
            caps = ", ".join(fit.model.capabilities) if fit.model.capabilities else "None"
            tip = (
                f"{fit.model.name}\n"
                f"Use case: {fit.model.use_case}\n"
                f"Capabilities: {caps}\n"
                f"License: {fit.model.license}"
            )
            if not is_engine_compatible(fit.model.format):
                supported = ", ".join(sorted(SUPPORTED_FORMATS)).upper()
                tip += (
                    f"\n\n⚠ Format '{fit.model.format}' won't run on the local "
                    f"engines here (they support: {supported})."
                )
            return tip
        elif col == "provider":
            if is_trusted_source(fit.model):
                return f"✓ {fit.model.provider}\nTrusted first-party publisher."
            tip = (
                f"⚠ {fit.model.provider}\n"
                "Unverified source — not a recognised first-party publisher.\n"
                "Review the repo before downloading."
            )
            if is_reupload(fit.model):
                tip += f"\nCommunity re-upload / quant of: {fit.model.base_model}"
            return tip
        elif col == "score":
            sc = fit.score_components
            return (
                f"Quality: {sc.quality:.1f}\n"
                f"Speed: {sc.speed:.1f}\n"
                f"Fit: {sc.fit:.1f}"
            )
        elif col == "mem_pct":
            return (
                f"Required: {fit.memory_required_gb:.1f} GB\n"
                f"Available: {fit.memory_available_gb:.1f} GB\n"
                f"Utilization: {fit.utilization_pct:.1f}%"
            )
        elif col == "fit":
            return (
                f"{fit.fit_level.value} — {fit.fit_level.short_hint}\n"
                f"Memory utilization: {fit.utilization_pct:.0f}%\n"
                "\n"
                "Perfect  ≤60%   plenty of headroom\n"
                "Good     60–80% comfortable\n"
                "Marginal 80–95% barely fits\n"
                "Too Tight >95%  doesn't fit"
            )
        return ""


class ModelFilterProxy(QSortFilterProxyModel):
    """Proxy model that filters by search text and dropdown criteria."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._search_text = ""
        self._provider = ""
        self._usecase = ""
        self._fit = ""
        self._quant = ""
        self._license = ""
        self._capability = ""
        self._installed_only = False
        self._min_tps = 0.0
        self.setDynamicSortFilter(True)

    def set_filters(
        self,
        search: str = "",
        provider: str = "",
        usecase: str = "",
        fit: str = "",
        quant: str = "",
        license: str = "",
        capability: str = "",
        installed_only: bool = False,
        min_tps: float = 0.0,
    ):
        self._search_text = search.lower()
        self._provider = provider.lower()
        self._usecase = usecase.lower()
        self._fit = fit
        self._quant = quant
        self._license = license.lower()
        self._capability = capability.lower()
        self._installed_only = installed_only
        self._min_tps = max(0.0, float(min_tps))
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if not isinstance(model, ModelTableModel):
            return True

        fit = model.get_fit(source_row)
        if fit is None:
            return False

        # Search text — match against name and provider
        if self._search_text:
            searchable = f"{fit.model.name} {fit.model.provider}".lower()
            if self._search_text not in searchable:
                return False

        # Provider filter
        if self._provider and fit.model.provider.lower() != self._provider:
            return False

        # Use case filter
        if self._usecase and fit.model.use_case.lower() != self._usecase:
            return False

        # Fit level filter
        if self._fit and fit.fit_level.value != self._fit:
            return False

        # Quantization filter (match either catalog quant or best_quant)
        if self._quant:
            model_q = (fit.model.quantization or "").lower()
            best_q = (fit.best_quant or "").lower()
            if self._quant.lower() not in (model_q, best_q):
                return False

        # License filter (substring match handles things like "llama3.1" vs "llama3")
        if self._license:
            if self._license not in (fit.model.license or "").lower():
                return False

        # Capability filter
        if self._capability:
            caps_lower = [c.lower() for c in (fit.model.capabilities or [])]
            if self._capability not in caps_lower:
                return False

        # Installed-only toggle
        if self._installed_only and not getattr(fit, "installed", False):
            return False

        # Min TPS filter — hide too-slow models
        if self._min_tps > 0 and fit.estimated_tps < self._min_tps:
            return False

        return True

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """Sort using raw UserRole values."""
        left_val = self.sourceModel().data(left, Qt.ItemDataRole.UserRole)
        right_val = self.sourceModel().data(right, Qt.ItemDataRole.UserRole)
        if left_val is None or right_val is None:
            return False
        try:
            return left_val < right_val
        except TypeError:
            return str(left_val) < str(right_val)


class ModelTableView(QTableView):
    """Styled table view for model fits."""

    model_selected = pyqtSignal(object)  # ModelFit or None
    download_requested = pyqtSignal(object)  # ModelFit
    run_requested = pyqtSignal(object)  # ModelFit

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_view()
        self._setup_context_menu()

    def _setup_view(self):
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        # Revert word wrap to False to prevent layout freezing
        self.setWordWrap(False)

        # Column sizing
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        # Revert to Interactive to avoid freezing on massive datasets (like 1000+ models)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(60)

    def _setup_context_menu(self):
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _current_fit(self) -> "ModelFit | None":
        idx = self.currentIndex()
        if not idx.isValid():
            return None
        proxy = self.model()
        source_idx = proxy.mapToSource(idx)
        source_model = proxy.sourceModel()
        if isinstance(source_model, ModelTableModel):
            return source_model.get_fit(source_idx.row())
        return None

    def _show_context_menu(self, pos):
        fit = self._current_fit()
        if fit is None:
            return

        menu = QMenu(self)

        copy_name = QAction("Copy Name", self)
        copy_name.triggered.connect(lambda: self._copy_to_clipboard(fit.model.name))
        menu.addAction(copy_name)

        copy_score = QAction("Copy Score", self)
        copy_score.triggered.connect(lambda: self._copy_to_clipboard(f"{fit.score:.1f}"))
        menu.addAction(copy_score)

        copy_info = QAction("Copy All Info", self)
        copy_info.triggered.connect(lambda: self._copy_to_clipboard(self._full_info(fit)))
        menu.addAction(copy_info)

        menu.addSeparator()

        download_action = QAction("Download…", self)
        download_action.triggered.connect(lambda: self.download_requested.emit(fit))
        menu.addAction(download_action)

        run_action = QAction("Run (Chat)…", self)
        can_run = getattr(fit, "installed", False) and fit.fit_level != FitLevel.TOO_TIGHT
        run_action.setEnabled(can_run)
        run_action.triggered.connect(lambda: self.run_requested.emit(fit))
        menu.addAction(run_action)

        menu.exec(self.viewport().mapToGlobal(pos))

    def _copy_to_clipboard(self, text: str):
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    def _full_info(self, fit) -> str:
        m = fit.model
        return (
            f"{m.name} ({m.provider})\n"
            f"  Parameters: {m.parameter_count}\n"
            f"  Use case: {m.use_case}\n"
            f"  Quantization: {fit.best_quant}\n"
            f"  Context: {m.ctx_length} tokens\n"
            f"  Memory: {fit.memory_required_gb:.1f} / {fit.memory_available_gb:.1f} GB\n"
            f"  Run mode: {fit.run_mode.value}\n"
            f"  Fit level: {fit.fit_level.value}\n"
            f"  Estimated TPS: {fit.estimated_tps:.1f} tok/s\n"
            f"  Score: {fit.score:.1f}/100\n"
            f"  License: {m.license or 'Unknown'}\n"
        )

    def set_default_column_widths(self):
        """Set sensible default column widths."""
        widths = {
            0: 36,   # Checkbox
            1: 250,  # Model Name
            2: 120,  # Provider
            3: 110,  # Params (PARAMETERS)
            4: 125,  # Score (OVERALL SCORE)
            5: 85,   # TPS (EST. TPS)
            6: 120,  # Quant (QUANTIZATION)
            7: 100,  # Disk (DISK SIZE)
            8: 100,  # Run Mode (RUN TYPE)
            9: 110,  # Mem % (RAM USAGE)
            10: 135, # Context (CONTEXT LENGTH)
            11: 120, # Fit (FIT QUALITY)
        }
        for col, width in widths.items():
            self.setColumnWidth(col, width)
        # Don't let checkbox column stretch
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)

    def mousePressEvent(self, event):
        """Toggle selection: clicking the already-selected row deselects it.
        Column 0 (checkbox) toggles the check state manually."""
        idx = self.indexAt(event.pos())
        if idx.isValid() and idx.column() == 0:
            # Manually toggle checkbox via the source model
            proxy = self.model()
            source_idx = proxy.mapToSource(idx)
            source_model = proxy.sourceModel()
            if isinstance(source_model, ModelTableModel):
                current = source_model.data(source_idx, Qt.ItemDataRole.CheckStateRole)
                # Handle both enum and integer returns from Qt correctly
                is_currently_checked = current in (Qt.CheckState.Checked, 2)
                new_val = Qt.CheckState.Unchecked if is_currently_checked else Qt.CheckState.Checked
                source_model.setData(source_idx, new_val, Qt.ItemDataRole.CheckStateRole)
            return
        if idx.isValid():
            sel = self.selectionModel().selectedRows()
            if sel and sel[0].row() == idx.row():
                self.clearSelection()
                self.model_selected.emit(None)
                return
        super().mousePressEvent(event)

    def selectionChanged(self, selected, deselected):
        super().selectionChanged(selected, deselected)
        indexes = self.selectionModel().selectedRows()
        if indexes:
            proxy = self.model()
            source_idx = proxy.mapToSource(indexes[0])
            source_model = proxy.sourceModel()
            if isinstance(source_model, ModelTableModel):
                fit = source_model.get_fit(source_idx.row())
                self.model_selected.emit(fit)
        else:
            self.model_selected.emit(None)
