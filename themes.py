"""Dark/Light QSS theme system with semantic color slots."""

from dataclasses import dataclass


@dataclass
class ThemeColors:
    """Complete color palette for one theme."""

    name: str

    # General
    bg: str
    bg_alt: str
    fg: str
    fg_muted: str
    border: str
    border_light: str

    # Accent
    accent: str
    accent_hover: str
    accent_text: str

    # Status
    good: str
    warning: str
    error: str
    info: str

    # Fit levels
    fit_perfect: str
    fit_good: str
    fit_marginal: str
    fit_tight: str

    # Run modes
    mode_gpu: str
    mode_moe: str
    mode_offload: str
    mode_cpu: str

    # Scores (high / mid / low)
    score_high: str
    score_mid: str
    score_low: str

    # Selection
    selection_bg: str
    selection_fg: str

    # Header
    header_bg: str
    header_fg: str

    # Input
    input_bg: str
    input_border: str
    input_focus: str

    # Scrollbar
    scrollbar_bg: str
    scrollbar_handle: str


DARK_THEME = ThemeColors(
    name="dark",
    bg="#1e1e2e",
    bg_alt="#181825",
    fg="#cdd6f4",
    fg_muted="#6c7086",
    border="#313244",
    border_light="#45475a",
    accent="#89b4fa",
    accent_hover="#74c7ec",
    accent_text="#1e1e2e",
    good="#a6e3a1",
    warning="#f9e2af",
    error="#f38ba8",
    info="#89b4fa",
    fit_perfect="#a6e3a1",
    fit_good="#94e2d5",
    fit_marginal="#f9e2af",
    fit_tight="#f38ba8",
    mode_gpu="#a6e3a1",
    mode_moe="#cba6f7",
    mode_offload="#f9e2af",
    mode_cpu="#f38ba8",
    score_high="#a6e3a1",
    score_mid="#f9e2af",
    score_low="#f38ba8",
    selection_bg="#45475a",
    selection_fg="#cdd6f4",
    header_bg="#181825",
    header_fg="#bac2de",
    input_bg="#313244",
    input_border="#45475a",
    input_focus="#89b4fa",
    scrollbar_bg="#181825",
    scrollbar_handle="#45475a",
)

LIGHT_THEME = ThemeColors(
    name="light",
    bg="#eff1f5",
    bg_alt="#e6e9ef",
    fg="#4c4f69",
    fg_muted="#9ca0b0",
    border="#ccd0da",
    border_light="#bcc0cc",
    accent="#1e66f5",
    accent_hover="#2a6ef6",
    accent_text="#ffffff",
    good="#40a02b",
    warning="#df8e1d",
    error="#d20f39",
    info="#1e66f5",
    fit_perfect="#40a02b",
    fit_good="#179299",
    fit_marginal="#df8e1d",
    fit_tight="#d20f39",
    mode_gpu="#40a02b",
    mode_moe="#8839ef",
    mode_offload="#df8e1d",
    mode_cpu="#d20f39",
    score_high="#40a02b",
    score_mid="#df8e1d",
    score_low="#d20f39",
    selection_bg="#ccd0da",
    selection_fg="#4c4f69",
    header_bg="#e6e9ef",
    header_fg="#5c5f77",
    input_bg="#ffffff",
    input_border="#ccd0da",
    input_focus="#1e66f5",
    scrollbar_bg="#e6e9ef",
    scrollbar_handle="#bcc0cc",
)

DRACULA_THEME = ThemeColors(
    name="dracula",
    bg="#282a36",
    bg_alt="#21222c",
    fg="#f8f8f2",
    fg_muted="#6272a4",
    border="#44475a",
    border_light="#6272a4",
    accent="#bd93f9",
    accent_hover="#d0aef7",
    accent_text="#282a36",
    good="#50fa7b",
    warning="#f1fa8c",
    error="#ff5555",
    info="#8be9fd",
    fit_perfect="#50fa7b",
    fit_good="#8be9fd",
    fit_marginal="#f1fa8c",
    fit_tight="#ff5555",
    mode_gpu="#50fa7b",
    mode_moe="#bd93f9",
    mode_offload="#f1fa8c",
    mode_cpu="#ff5555",
    score_high="#50fa7b",
    score_mid="#f1fa8c",
    score_low="#ff5555",
    selection_bg="#44475a",
    selection_fg="#f8f8f2",
    header_bg="#21222c",
    header_fg="#bd93f9",
    input_bg="#44475a",
    input_border="#6272a4",
    input_focus="#bd93f9",
    scrollbar_bg="#21222c",
    scrollbar_handle="#6272a4",
)

NORD_THEME = ThemeColors(
    name="nord",
    bg="#2e3440",
    bg_alt="#3b4252",
    fg="#eceff4",
    fg_muted="#81a1c1",
    border="#434c5e",
    border_light="#4c566a",
    accent="#88c0d0",
    accent_hover="#8fbcbb",
    accent_text="#2e3440",
    good="#a3be8c",
    warning="#ebcb8b",
    error="#bf616a",
    info="#81a1c1",
    fit_perfect="#a3be8c",
    fit_good="#8fbcbb",
    fit_marginal="#ebcb8b",
    fit_tight="#bf616a",
    mode_gpu="#a3be8c",
    mode_moe="#b48ead",
    mode_offload="#ebcb8b",
    mode_cpu="#bf616a",
    score_high="#a3be8c",
    score_mid="#ebcb8b",
    score_low="#bf616a",
    selection_bg="#434c5e",
    selection_fg="#eceff4",
    header_bg="#3b4252",
    header_fg="#88c0d0",
    input_bg="#3b4252",
    input_border="#4c566a",
    input_focus="#88c0d0",
    scrollbar_bg="#3b4252",
    scrollbar_handle="#4c566a",
)

GRUVBOX_THEME = ThemeColors(
    name="gruvbox",
    bg="#282828",
    bg_alt="#1d2021",
    fg="#ebdbb2",
    fg_muted="#a89984",
    border="#3c3836",
    border_light="#504945",
    accent="#fabd2f",
    accent_hover="#fe8019",
    accent_text="#282828",
    good="#b8bb26",
    warning="#fabd2f",
    error="#fb4934",
    info="#83a598",
    fit_perfect="#b8bb26",
    fit_good="#83a598",
    fit_marginal="#fabd2f",
    fit_tight="#fb4934",
    mode_gpu="#b8bb26",
    mode_moe="#d3869b",
    mode_offload="#fabd2f",
    mode_cpu="#fb4934",
    score_high="#b8bb26",
    score_mid="#fabd2f",
    score_low="#fb4934",
    selection_bg="#3c3836",
    selection_fg="#ebdbb2",
    header_bg="#1d2021",
    header_fg="#fabd2f",
    input_bg="#3c3836",
    input_border="#504945",
    input_focus="#fabd2f",
    scrollbar_bg="#1d2021",
    scrollbar_handle="#504945",
)

SOLARIZED_THEME = ThemeColors(
    name="solarized",
    bg="#002b36",
    bg_alt="#073642",
    fg="#eee8d5",
    fg_muted="#93a1a1",
    border="#073642",
    border_light="#586e75",
    accent="#268bd2",
    accent_hover="#2aa198",
    accent_text="#002b36",
    good="#859900",
    warning="#b58900",
    error="#dc322f",
    info="#268bd2",
    fit_perfect="#859900",
    fit_good="#2aa198",
    fit_marginal="#b58900",
    fit_tight="#dc322f",
    mode_gpu="#859900",
    mode_moe="#d33682",
    mode_offload="#b58900",
    mode_cpu="#dc322f",
    score_high="#859900",
    score_mid="#b58900",
    score_low="#dc322f",
    selection_bg="#073642",
    selection_fg="#eee8d5",
    header_bg="#073642",
    header_fg="#268bd2",
    input_bg="#073642",
    input_border="#586e75",
    input_focus="#268bd2",
    scrollbar_bg="#073642",
    scrollbar_handle="#586e75",
)

THEMES: dict[str, ThemeColors] = {
    "dark": DARK_THEME,
    "light": LIGHT_THEME,
    "dracula": DRACULA_THEME,
    "nord": NORD_THEME,
    "gruvbox": GRUVBOX_THEME,
    "solarized": SOLARIZED_THEME,
}

# Display labels for the theme picker
THEME_LABELS: dict[str, str] = {
    "dark": "Dark (Catppuccin Mocha)",
    "light": "Light (Catppuccin Latte)",
    "dracula": "Dracula",
    "nord": "Nord",
    "gruvbox": "Gruvbox",
    "solarized": "Solarized Dark",
}


def get_theme(name: str) -> ThemeColors:
    return THEMES.get(name, DARK_THEME)


def generate_qss(c: ThemeColors) -> str:
    """Generate a complete QSS stylesheet from the color palette."""
    # Pre-compute accent RGB for rgba() usage
    _ah = c.accent.lstrip("#")
    c_accent_rgb = f"{int(_ah[0:2], 16)},{int(_ah[2:4], 16)},{int(_ah[4:6], 16)}"
    return f"""
/* ========== Global ========== */
QMainWindow, QDialog {{
    background: transparent;
    color: {c.fg};
}}

/* ========== Sidebar (painted — minimal QSS) ========== */
QWidget#sidebar {{
    background: transparent;
}}

/* ========== Sidebar Navigation (BitBuddy-style) ========== */
QPushButton#sidebar_nav {{
    background: transparent;
    border: none;
    color: {c.fg_muted};
    font: 10pt 'Segoe UI';
    padding: 10px 14px;
    border-radius: 10px;
    text-align: left;
    min-width: 0;
}}

QPushButton#sidebar_nav:hover {{
    background: rgba({c_accent_rgb},0.1);
    color: {c.fg};
}}

QPushButton#sidebar_nav:checked {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 rgba({c_accent_rgb},0.25), stop:1 rgba({c_accent_rgb},0.05));
    color: {c.accent};
    border-left: 3px solid {c.accent};
}}

/* ========== Header Bar (painted — minimal QSS) ========== */
QLabel#header_title {{
    background: transparent;
}}

QWidget#header_sysinfo {{
    background: transparent;
    border: none;
}}

QWidget#system_strip {{
    background: transparent;
    border-bottom: 1px solid {c.border};
    padding: 0 8px;
}}

QFrame#sys_card {{
    background: rgba({c_accent_rgb},0.06);
    border: 1px solid {c.border};
    border-radius: 12px;
}}

QFrame#sys_card:hover {{
    background: rgba({c_accent_rgb},0.12);
    border-color: {c.accent};
}}

/* Version badge styled inline — no QSS override needed */

/* ========== Window Control Buttons ========== */
QPushButton#win_minimize_btn {{
    background: transparent;
    border: none;
    border-radius: 5px;
    color: {c.fg_muted};
    font: bold 12pt;
    padding: 0;
    min-width: 0;
}}

QPushButton#win_minimize_btn:hover {{
    color: {c.fg};
    background: rgba(100,116,139,0.15);
}}

QPushButton#win_close_btn {{
    background: transparent;
    border: none;
    border-radius: 5px;
    color: {c.fg_muted};
    font: bold 14pt;
    padding: 0;
    min-width: 0;
}}

QPushButton#win_close_btn:hover {{
    color: #ef4444;
    background: rgba(239,68,68,0.1);
}}

/* ========== Theme Picker Flyout ========== */
QFrame#theme_picker {{
    background-color: {c.bg_alt};
    border: 1px solid {c.border};
    border-radius: 12px;
}}

QPushButton#theme_choice {{
    background: transparent;
    color: {c.fg};
    border: 1px solid transparent;
    border-radius: 8px;
    text-align: left;
    padding: 4px 10px;
    font-size: 12px;
}}

QPushButton#theme_choice:hover {{
    background-color: {c.selection_bg};
    border-color: {c.border};
}}

QPushButton#theme_choice[current="true"] {{
    background-color: {c.accent};
    color: {c.accent_text};
    border-color: {c.accent};
    font-weight: 600;
}}

/* ========== Section Titles ========== */
QLabel[class="section_title"] {{
    font-size: 13px;
    font-weight: 700;
    color: {c.fg_muted};
    text-transform: uppercase;
    letter-spacing: 1px;
    background: transparent;
    padding: 0 2px;
}}

QWidget#section {{
    background: transparent;
}}

/* ========== HW Sim Buttons ========== */
QPushButton#hw_apply_btn {{
    background-color: {c.selection_bg};
    color: {c.fg};
    border: 1px solid {c.border};
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
}}

QPushButton#hw_apply_btn:hover {{
    background-color: {c.accent};
    color: {c.accent_text};
    border-color: {c.accent};
}}

QPushButton#hw_reset_btn {{
    background-color: transparent;
    color: {c.fg_muted};
    border: 1px solid {c.border};
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 12px;
}}

QPushButton#hw_reset_btn:hover {{
    background-color: {c.selection_bg};
    color: {c.fg};
}}

QFrame#filter_section {{
    background: transparent;
}}

/* ========== Stat Cards ========== */
QFrame#stat_card {{
    background-color: {c.bg_alt};
    border: 1px solid {c.border};
    border-radius: 12px;
}}

QLabel#stat_icon {{
    font-size: 20px;
    background: transparent;
}}

QLabel#stat_value {{
    font-size: 20px;
    font-weight: bold;
    color: {c.fg};
    background: transparent;
    padding: 0;
}}

QLabel#stat_title {{
    font-size: 11px;
    color: {c.fg_muted};
    background: transparent;
    padding: 0;
}}

/* ========== Content Cards ========== */
QFrame#card {{
    background-color: {c.bg};
    border: 1px solid {c.border};
    border-radius: 12px;
}}

QWidget {{
    background-color: {c.bg};
    color: {c.fg};
    font-family: "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
    font-size: 13px;
}}

/* ========== Labels ========== */
QLabel {{
    background: transparent;
    color: {c.fg};
    padding: 2px;
}}

QLabel[class="muted"] {{
    color: {c.fg_muted};
}}

QLabel[class="title"] {{
    font-size: 15px;
    font-weight: bold;
    color: {c.fg};
}}

QLabel[class="accent"] {{
    color: {c.accent};
    font-weight: bold;
}}

/* ========== Push Button ========== */
QPushButton {{
    background-color: {c.accent};
    color: {c.accent_text};
    border: none;
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 600;
    font-size: 13px;
}}

QPushButton:hover {{
    background-color: {c.accent_hover};
}}

QPushButton:pressed {{
    background-color: {c.accent};
    padding-top: 8px;
}}

QPushButton:disabled {{
    background-color: {c.border};
    color: {c.fg_muted};
}}

QPushButton[class="secondary"] {{
    background-color: {c.input_bg};
    color: {c.fg};
    border: 1px solid {c.border};
}}

QPushButton[class="secondary"]:hover {{
    background-color: {c.selection_bg};
    border-color: {c.accent};
}}

/* ========== Line Edit ========== */
QLineEdit {{
    background-color: {c.input_bg};
    color: {c.fg};
    border: 1px solid {c.input_border};
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 13px;
    selection-background-color: {c.accent};
    selection-color: {c.accent_text};
}}

QLineEdit:focus {{
    border-color: {c.input_focus};
    border-width: 2px;
    padding: 6px 11px;
}}

QLineEdit::placeholder {{
    color: {c.fg_muted};
}}

/* ========== Combo Box ========== */
QComboBox {{
    background-color: {c.input_bg};
    color: {c.fg};
    border: 1px solid {c.input_border};
    border-radius: 6px;
    padding: 6px 12px;
    min-width: 100px;
    font-size: 13px;
}}

QComboBox:hover {{
    border-color: {c.accent};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {c.fg_muted};
    margin-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {c.bg_alt};
    color: {c.fg};
    border: 1px solid {c.border};
    border-radius: 6px;
    selection-background-color: {c.selection_bg};
    selection-color: {c.selection_fg};
    padding: 4px;
}}

/* ========== Table View ========== */
QTableView {{
    background-color: {c.bg};
    color: {c.fg};
    gridline-color: {c.border};
    border: 1px solid {c.border};
    border-radius: 12px;
    selection-background-color: transparent;
    selection-color: {c.fg};
    font-size: 13px;
    outline: none;
}}

QTableView::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {c.border};
    outline: none;
}}

QTableView::item:selected {{
    background-color: transparent;
    outline: none;
}}

QTableView::item:hover {{
    background-color: {c.border};
}}

QHeaderView {{
    background-color: {c.header_bg};
}}

QHeaderView::section {{
    background-color: {c.header_bg};
    color: {c.header_fg};
    border: none;
    border-bottom: 2px solid {c.border};
    border-right: 1px solid {c.border};
    padding: 8px 8px;
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
}}

QHeaderView::section:hover {{
    background-color: {c.selection_bg};
    color: {c.fg};
}}

/* ========== Splitter ========== */
QSplitter::handle {{
    background-color: {c.border};
    width: 2px;
    margin: 0 4px;
}}

QSplitter::handle:hover {{
    background-color: {c.accent};
}}

/* ========== Scroll Bar ========== */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 4px 2px;
    border: none;
}}

QScrollBar::handle:vertical {{
    background: rgba({c_accent_rgb},0.35);
    min-height: 40px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: rgba({c_accent_rgb},0.55);
}}

QScrollBar::handle:vertical:pressed {{
    background: rgba({c_accent_rgb},0.7);
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px 4px;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background: rgba({c_accent_rgb},0.35);
    min-width: 40px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal:hover {{
    background: rgba({c_accent_rgb},0.55);
}}

QScrollBar::handle:horizontal:pressed {{
    background: rgba({c_accent_rgb},0.7);
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ========== Status Bar ========== */
QStatusBar {{
    background: transparent;
    color: {c.fg_muted};
    border-top: 1px solid {c.border};
    padding: 4px 8px;
    font-size: 12px;
}}

QStatusBar QLabel {{
    color: {c.fg_muted};
    padding: 0 8px;
    font-size: 12px;
}}

/* ========== Group Box ========== */
QGroupBox {{
    background-color: {c.bg_alt};
    border: 1px solid {c.border};
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
    font-size: 13px;
}}

QGroupBox::title {{
    color: {c.fg};
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}

/* ========== Tab Widget ========== */
QTabWidget::pane {{
    background-color: {c.bg};
    border: 1px solid {c.border};
    border-radius: 8px;
}}

QTabBar::tab {{
    background-color: {c.bg_alt};
    color: {c.fg_muted};
    border: none;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-size: 13px;
}}

QTabBar::tab:selected {{
    background-color: {c.bg};
    color: {c.fg};
    border-bottom: 2px solid {c.accent};
}}

QTabBar::tab:hover:!selected {{
    background-color: {c.selection_bg};
    color: {c.fg};
}}

/* ========== SpinBox ========== */
QSpinBox, QDoubleSpinBox {{
    background-color: {c.input_bg};
    color: {c.fg};
    border: 1px solid {c.input_border};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 13px;
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {c.input_focus};
}}

QPushButton#spin_minus_btn, QPushButton#spin_plus_btn {{
    background: {c.selection_bg};
    border: 1px solid {c.input_border};
    border-radius: 6px;
}}

QPushButton#spin_minus_btn:hover, QPushButton#spin_plus_btn:hover {{
    background: {c.accent};
    border-color: {c.accent};
}}

/* ========== Progress Bar ========== */
QProgressBar {{
    background-color: {c.input_bg};
    border: 1px solid {c.border};
    border-radius: 4px;
    text-align: center;
    color: {c.fg};
    font-size: 11px;
    height: 8px;
}}

QProgressBar::chunk {{
    background-color: {c.accent};
    border-radius: 3px;
}}

/* ========== Tooltip ========== */
QToolTip {{
    background-color: {c.bg_alt};
    color: {c.fg};
    border: 1px solid {c.border};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}

/* ========== Menu ========== */
QMenu {{
    background-color: {c.bg_alt};
    color: {c.fg};
    border: 1px solid {c.border};
    border-radius: 8px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 24px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {c.selection_bg};
    color: {c.selection_fg};
}}

QMenu::separator {{
    height: 1px;
    background-color: {c.border};
    margin: 4px 8px;
}}
"""
