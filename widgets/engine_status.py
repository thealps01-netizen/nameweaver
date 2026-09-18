"""Engine status pill — shows the state of local LLM runtimes.

A single chip-style widget that summarises the health of all detected
providers (Ollama / LM Studio / llama.cpp / Docker Model Runner) into one
of three user-facing states:

- 🟢 READY       — at least one provider is answering
- 🟡 OFF         — something is installed but not running; one-click start
- 🔴 NOT_INSTALLED — nothing usable; offer install flow

Clicking the pill opens a popup menu listing each provider and the action
the user can take. Non-technical users never see the word "provider" —
they see "motor" (engine) and one call-to-action.

Signals:
  start_requested(str)    — UI wants to launch ``start_action`` (e.g. "start_ollama")
  install_requested(str)  — UI wants to install provider by name
  open_guide_requested(str) — fallback guided modal for provider
"""

from __future__ import annotations

import qtawesome as qta
from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from providers import ProviderState, ProviderStatus
from themes import ThemeColors, get_theme


def _overall_state(providers: list[ProviderStatus]) -> ProviderState:
    """Collapse a list of provider statuses into one user-facing state."""
    if any(p.state == ProviderState.READY for p in providers):
        return ProviderState.READY
    if any(p.state == ProviderState.INSTALLED_OFF for p in providers):
        return ProviderState.INSTALLED_OFF
    return ProviderState.NOT_INSTALLED


def _pick_primary(providers: list[ProviderStatus]) -> ProviderStatus | None:
    """Choose which provider to surface as 'the' engine in the pill label."""
    # Priority: READY > INSTALLED_OFF > NOT_INSTALLED
    # Within each bucket, Ollama first (simplest), then LM Studio, then others.
    priority_name = ("Ollama", "LM Studio", "Docker Model Runner", "llama.cpp")
    for target_state in (
        ProviderState.READY,
        ProviderState.INSTALLED_OFF,
        ProviderState.NOT_INSTALLED,
    ):
        for name in priority_name:
            for p in providers:
                if p.name == name and p.state == target_state:
                    return p
    return providers[0] if providers else None


class _ProviderRow(QFrame):
    """One engine's row in the popup, updated in place.

    The popup runs its own event loop, so detection results and busy flags can
    change while it is open. Replacing the row widget does not work —
    QWidgetAction keeps the first widget it was handed — so the row updates
    itself, and it can only ever update from the engine it was built for.
    """

    def __init__(self, provider_name: str, on_row_clicked, parent: QWidget | None = None):
        super().__init__(parent)
        self.provider_name = provider_name
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mousePressEvent = lambda _e: on_row_clicked(provider_name)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        self._dot = QLabel("●")
        lay.addWidget(self._dot)

        self._name = QLabel(provider_name)
        self._name.setStyleSheet("font-size: 12px; font-weight: 600;")
        lay.addWidget(self._name)

        self._check = QLabel()
        self._check.setVisible(False)
        lay.addWidget(self._check)

        self._state = QLabel("")
        lay.addWidget(self._state)
        lay.addStretch(1)

        self._action_area = QWidget()
        self._action_lay = QHBoxLayout(self._action_area)
        self._action_lay.setContentsMargins(0, 0, 0, 0)
        self._action_lay.setSpacing(6)
        lay.addWidget(self._action_area)

    def update_from(
        self,
        p: ProviderStatus,
        t: ThemeColors,
        *,
        featured_name: str = "",
        busy: str = "",
        handlers: dict | None = None,
    ) -> None:
        """Re-render this row from its engine (``busy`` is "" | "start" | "stop")."""
        handlers = handlers or {}
        is_featured = featured_name == self.provider_name

        self.setStyleSheet(
            f"QFrame {{ background: transparent; border-radius: 8px; }}"
            f" QLabel {{ color: {t.fg}; background: transparent; border: none; }}"
        )
        dot_color = (
            t.good
            if p.state == ProviderState.READY
            else t.warning
            if p.state == ProviderState.INSTALLED_OFF
            else t.error
        )
        self._dot.setStyleSheet(f"color: {dot_color}; font-size: 14px;")
        self._name.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {t.fg};")

        self._check.setVisible(is_featured)
        if is_featured:
            self._check.setPixmap(
                qta.icon("mdi6.check-circle", color=t.accent).pixmap(QSize(15, 15))
            )

        state_text = {
            ProviderState.READY: "running",
            ProviderState.INSTALLED_OFF: "off",
            ProviderState.NOT_INSTALLED: "not installed",
        }[p.state]
        self._state.setText(f"— {state_text}")
        self._state.setStyleSheet(f"color: {t.fg_muted}; font-size: 11px;")

        self._rebuild_action(p, t, busy, handlers)

    # ------------------------------------------------------------------ action

    def _clear_action(self) -> None:
        while self._action_lay.count():
            item = self._action_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild_action(self, p: ProviderStatus, t: ThemeColors, busy: str, handlers: dict) -> None:
        self._clear_action()

        if busy:
            label = QLabel("Starting…" if busy == "start" else "Stopping…")
            label.setStyleSheet(
                f"color: {t.fg_muted}; font-size: 11px; font-style: italic;"
                f" background: transparent; border: none;"
            )
            self._action_lay.addWidget(label)
            spinner = QPushButton()
            spinner.setFixedSize(22, 22)
            spinner.setFlat(True)
            spinner.setEnabled(False)
            spinner.setCursor(Qt.CursorShape.ArrowCursor)
            spinner.setStyleSheet(
                "QPushButton { background: transparent; border: none; }"
                " QPushButton:disabled { background: transparent; }"
            )
            spinner.setIcon(qta.icon("mdi6.loading", color=t.accent, animation=qta.Spin(spinner)))
            spinner.setIconSize(QSize(16, 16))
            self._action_lay.addWidget(spinner)
            return

        outline = (
            f"QPushButton {{ background: transparent; color: {t.accent};"
            f" border: 1px solid {t.accent}; border-radius: 6px;"
            f" padding: 3px 10px; font-size: 11px; font-weight: 600; }}"
            f" QPushButton:hover {{ background: {t.accent}; color: {t.accent_text}; }}"
        )
        solid_warning = (
            f"QPushButton {{ background: transparent; color: {t.warning};"
            f" border: 1px solid {t.warning}; border-radius: 6px;"
            f" padding: 3px 10px; font-size: 11px; font-weight: 600; }}"
            f" QPushButton:hover {{ background: {t.warning}; color: {t.accent_text}; }}"
        )
        solid_accent = (
            f"QPushButton {{ background: {t.accent}; color: {t.accent_text};"
            f" border: none; border-radius: 6px; padding: 3px 10px;"
            f" font-size: 11px; font-weight: 600; }}"
            f" QPushButton:hover {{ background: {t.accent_hover}; }}"
        )

        if p.state == ProviderState.READY and p.stop_action:
            btn = QPushButton("Stop")
            btn.setStyleSheet(solid_warning)
            btn.clicked.connect(
                lambda _=False: handlers.get("stop", lambda *_a: None)(
                    p.stop_action, self.provider_name
                )
            )
        elif p.state == ProviderState.INSTALLED_OFF and p.start_action:
            btn = QPushButton("Start")
            btn.setStyleSheet(solid_accent)
            btn.clicked.connect(
                lambda _=False: handlers.get("start", lambda *_a: None)(
                    p.start_action, self.provider_name
                )
            )
        elif p.state == ProviderState.NOT_INSTALLED:
            btn = QPushButton("Install")
            btn.setStyleSheet(outline)
            btn.clicked.connect(lambda _=False: handlers.get("install", lambda _n: None)(p.name))
        else:
            return

        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action_lay.addWidget(btn)


class EngineStatusPill(QFrame):
    """Clickable status chip for the system bar."""

    start_requested = pyqtSignal(str)  # start_action key
    stop_requested = pyqtSignal(str)  # stop_action key
    install_requested = pyqtSignal(str)  # provider name
    open_guide_requested = pyqtSignal(str)  # provider name

    def __init__(self, theme_name: str = "dark", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("engine_pill")
        self._theme_name = theme_name
        self._providers: list[ProviderStatus] = []
        self._busy_names: set[str] = set()  # providers mid-start/stop
        self._busy_actions: dict[str, str] = {}  # name -> "start" | "stop"
        self._current_menu: QMenu | None = None
        self._popup_rows: dict[str, _ProviderRow] = {}  # engine name -> its row
        self._selected_name: str | None = None  # user-chosen featured engine

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        self._dot = QLabel("●")
        self._dot.setStyleSheet("background: transparent; border: none; font-size: 16px;")
        layout.addWidget(self._dot)

        # Spinner shown in place of dot while a start/stop action is pending
        self._spinner = QPushButton()
        self._spinner.setFixedSize(20, 20)
        self._spinner.setFlat(True)
        self._spinner.setEnabled(False)
        self._spinner.setCursor(Qt.CursorShape.ArrowCursor)
        self._spinner.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            " QPushButton:disabled { background: transparent; }"
        )
        self._spinner.setVisible(False)
        layout.addWidget(self._spinner)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self._label = QLabel("MOTOR")
        self._label.setStyleSheet(
            "font-size: 10px; font-weight: 700; letter-spacing: 1px;"
            " background: transparent; border: none;"
        )
        text_col.addWidget(self._label)

        self._status = QLabel("…")
        self._status.setStyleSheet(
            "font-size: 13px; font-weight: 500; background: transparent; border: none;"
        )
        text_col.addWidget(self._status)

        layout.addLayout(text_col)
        layout.addStretch(1)

        self._action_btn = QPushButton("")
        self._action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action_btn.setVisible(False)
        self._action_btn.clicked.connect(self._on_action_clicked)
        layout.addWidget(self._action_btn)

        self._chevron = QLabel()
        self._chevron.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self._chevron)

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_theme()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_status(self, providers: list[ProviderStatus]) -> None:
        """Refresh the pill with the latest provider list.

        Clears any pending busy flags whose provider state actually changed,
        so the spinner disappears the moment the new detection confirms the
        action landed (avoids flicker where we'd briefly show the pre-action
        state between "worker finished" and "new detection arrived").
        """
        new_providers = list(providers)

        # Build old state map so we can detect transitions
        old_state = {p.name: p.state for p in self._providers}
        for name in list(self._busy_names):
            new_p = next((p for p in new_providers if p.name == name), None)
            if new_p is None:
                continue
            prev = old_state.get(name)
            # Transition happened → action landed, drop busy
            if prev is not None and new_p.state != prev:
                self._busy_names.discard(name)
                self._busy_actions.pop(name, None)

        self._providers = new_providers
        self._render()
        self._rebuild_popup_if_open()

    def _primary(self) -> ProviderStatus | None:
        """The engine featured in the pill: user's pick if still present, else auto."""
        if self._selected_name:
            for p in self._providers:
                if p.name == self._selected_name:
                    return p
        return _pick_primary(self._providers)

    def _select_engine(self, name: str) -> None:
        """User picked an engine from the popup — feature it in the pill."""
        self._selected_name = name
        self._render()
        self._rebuild_popup_if_open()

    def _render(self) -> None:
        """Paint the pill based on current providers + busy state."""
        state = _overall_state(self._providers)
        primary = self._primary()

        t = get_theme(self._theme_name)

        # Busy override — any provider mid-start/stop takes precedence
        if self._busy_names:
            busy_name = next(iter(self._busy_names))
            action = self._busy_actions.get(busy_name, "start")
            verb = "Starting" if action == "start" else "Stopping"
            self._dot.setVisible(False)
            self._spinner.setVisible(True)
            self._spinner.setIcon(
                qta.icon(
                    "mdi6.loading",
                    color=t.accent,
                    animation=qta.Spin(self._spinner),
                )
            )
            self._spinner.setIconSize(QSize(16, 16))
            self._status.setText(f"{busy_name} {verb.lower()}…")
            self._action_btn.setVisible(False)
            self._apply_theme()
            return

        # Not busy — restore static dot
        self._dot.setVisible(True)
        self._spinner.setVisible(False)

        if state == ProviderState.READY:
            self._dot.setStyleSheet(
                f"color: {t.good}; background: transparent; border: none; font-size: 16px;"
            )
            name = primary.name if primary else "—"
            self._status.setText(f"Ready · {name}")
            self._action_btn.setVisible(False)

        elif state == ProviderState.INSTALLED_OFF:
            self._dot.setStyleSheet(
                f"color: {t.warning}; background: transparent; border: none; font-size: 16px;"
            )
            name = primary.name if primary else "Engine"
            self._status.setText(f"{name} off")
            self._action_btn.setText("Start")
            self._action_btn.setVisible(True)

        else:  # NOT_INSTALLED
            self._dot.setStyleSheet(
                f"color: {t.error}; background: transparent; border: none; font-size: 16px;"
            )
            self._status.setText("Install required")
            self._action_btn.setText("Install")
            self._action_btn.setVisible(True)

        self._apply_theme()

    def refresh_theme(self, theme_name: str) -> None:
        self._theme_name = theme_name
        self._apply_theme()
        if self._providers:
            self.update_status(self._providers)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        t = get_theme(self._theme_name)
        self.setStyleSheet(
            f"QFrame#engine_pill {{ background: {t.bg_alt};"
            f" border: 1px solid {t.border}; border-radius: 12px; }}"
            f" QFrame#engine_pill:hover {{ border-color: {t.accent}; }}"
        )
        self._label.setStyleSheet(
            f"font-size: 10px; font-weight: 700; letter-spacing: 1px;"
            f" color: {t.fg_muted}; background: transparent; border: none;"
        )
        self._status.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {t.fg};"
            f" background: transparent; border: none;"
        )
        self._action_btn.setStyleSheet(
            f"QPushButton {{ background: {t.accent};"
            f" color: {t.accent_text}; border: none;"
            f" border-radius: 8px; padding: 4px 12px;"
            f" font-size: 12px; font-weight: 600; }}"
            f" QPushButton:hover {{ background: {t.accent_hover}; }}"
        )
        self._chevron.setPixmap(
            qta.icon("mdi6.chevron-down", color=t.fg_muted).pixmap(QSize(16, 16))
        )

    def _on_action_clicked(self) -> None:
        """Primary button → start or install depending on state."""
        primary = self._primary()
        if primary is None:
            return
        if primary.state == ProviderState.INSTALLED_OFF and primary.start_action:
            self.set_provider_busy(primary.name, True, "start")
            self.start_requested.emit(primary.start_action)
        elif primary.state == ProviderState.NOT_INSTALLED:
            self.install_requested.emit(primary.name)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            # Click on chip body (not the action button) shows the details popup
            child = self.childAt(event.pos())
            if child is not self._action_btn:
                self._show_details_popup()
        super().mousePressEvent(event)

    def set_provider_busy(self, name: str, busy: bool, action: str = "start") -> None:
        """Mark a provider as in-progress so its row shows a spinner.

        ``action`` is ``"start"`` or ``"stop"`` — controls the label shown
        ("Starting…" vs "Stopping…").
        """
        if busy:
            self._busy_names.add(name)
            self._busy_actions[name] = action
            # Safety: force-clear after 20s so the UI never gets stuck
            # spinning even if detection never sees a state transition.
            QTimer.singleShot(
                20_000,
                lambda n=name: self.set_provider_busy(n, False) if n in self._busy_names else None,
            )
        else:
            self._busy_names.discard(name)
            self._busy_actions.pop(name, None)
        # Instant feedback on both the pill and the open popup
        self._render()
        self._rebuild_popup_if_open()

    def _rebuild_popup_if_open(self) -> None:
        """Refresh open popup rows in place so spinners appear/disappear."""
        menu = self._current_menu
        if menu is None or not menu.isVisible():
            return
        self._refresh_popup_rows()

    def _refresh_popup_rows(self) -> None:
        """Re-render every open popup row, each from its own engine.

        Rows are held by engine name, never by position: detection re-runs every
        few seconds and the popup runs its own event loop, so a list that gained,
        lost or reordered an engine must not hand a row another engine's state.
        An engine that is gone keeps its last row rather than being relabelled.
        """
        t = get_theme(self._theme_name)
        by_name = {p.name: p for p in self._providers}
        featured = self._primary()
        for name, row in self._popup_rows.items():
            provider = by_name.get(name)
            if provider is None:
                continue
            row.update_from(
                provider,
                t,
                featured_name=featured.name if featured else "",
                busy=self._busy_actions.get(name, "") if name in self._busy_names else "",
                handlers=self._row_handlers(),
            )

    def _row_handlers(self) -> dict:
        return {
            "start": self._on_row_start,
            "stop": self._on_row_stop,
            "install": self.install_requested.emit,
        }

    def _on_row_start(self, action_key: str, name: str = "") -> None:
        if name:
            self.set_provider_busy(name, True, "start")
        self.start_requested.emit(action_key)

    def _on_row_stop(self, action_key: str, name: str = "") -> None:
        if name:
            self.set_provider_busy(name, True, "stop")
        self.stop_requested.emit(action_key)

    def _build_popup_menu(self) -> QMenu:
        """The per-provider popup, holding one live row per engine."""
        t = get_theme(self._theme_name)
        menu = QMenu(self)
        menu.setObjectName("engine_popup")
        self._popup_rows = {}
        featured = self._primary()

        for p in self._providers:
            row = _ProviderRow(p.name, self._select_engine)
            row.update_from(
                p,
                t,
                featured_name=featured.name if featured else "",
                busy=self._busy_actions.get(p.name, "") if p.name in self._busy_names else "",
                handlers=self._row_handlers(),
            )
            self._popup_rows[p.name] = row
            act = QWidgetAction(menu)
            act.setDefaultWidget(row)
            menu.addAction(act)
        return menu

    def _show_details_popup(self) -> None:
        """Popup listing every provider and its individual state/action."""
        if not self._providers:
            return
        menu = self._build_popup_menu()
        self._current_menu = menu

        try:
            menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
        finally:
            self._current_menu = None
            self._popup_rows = {}
