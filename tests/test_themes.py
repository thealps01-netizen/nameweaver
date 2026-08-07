"""Tests for the theme system."""

from themes import THEME_LABELS, THEMES, generate_qss, get_theme


class TestThemeRegistry:
    def test_six_themes(self):
        assert len(THEMES) == 6
        assert set(THEMES.keys()) == {
            "dark", "light", "dracula", "nord", "gruvbox", "solarized",
        }

    def test_all_themes_have_labels(self):
        for key in THEMES:
            assert key in THEME_LABELS
            assert THEME_LABELS[key]

    def test_get_theme_falls_back(self):
        # Unknown theme name → DARK
        assert get_theme("nonexistent").name == "dark"

    def test_all_themes_generate_qss(self):
        for key, colors in THEMES.items():
            qss = generate_qss(colors)
            assert len(qss) > 500
            # Each theme's bg color must appear in the generated QSS
            assert colors.bg in qss

    def test_theme_colors_unique_names(self):
        names = [t.name for t in THEMES.values()]
        assert len(names) == len(set(names))


class TestThemeSemanticSlots:
    def test_fit_colors_defined(self):
        for colors in THEMES.values():
            for slot in (colors.fit_perfect, colors.fit_good, colors.fit_marginal, colors.fit_tight):
                assert slot.startswith("#")
                assert len(slot) in (4, 7)

    def test_run_mode_colors_defined(self):
        for colors in THEMES.values():
            for slot in (colors.mode_gpu, colors.mode_moe, colors.mode_offload, colors.mode_cpu):
                assert slot.startswith("#")
