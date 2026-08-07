"""Tests for the engine status pill's state-collapsing logic.

These tests cover only the pure helper functions — the QWidget itself is
tested manually through GUI smoke tests.
"""

from providers import ProviderState, ProviderStatus
from widgets.engine_status import _overall_state, _pick_primary


def _mk(name: str, state: ProviderState) -> ProviderStatus:
    return ProviderStatus(name=name, state=state)


class TestOverallState:
    def test_any_ready_wins(self):
        providers = [
            _mk("Ollama", ProviderState.READY),
            _mk("LM Studio", ProviderState.INSTALLED_OFF),
            _mk("llama.cpp", ProviderState.NOT_INSTALLED),
        ]
        assert _overall_state(providers) == ProviderState.READY

    def test_installed_off_when_nothing_ready(self):
        providers = [
            _mk("Ollama", ProviderState.INSTALLED_OFF),
            _mk("LM Studio", ProviderState.NOT_INSTALLED),
        ]
        assert _overall_state(providers) == ProviderState.INSTALLED_OFF

    def test_all_missing(self):
        providers = [
            _mk("Ollama", ProviderState.NOT_INSTALLED),
            _mk("LM Studio", ProviderState.NOT_INSTALLED),
        ]
        assert _overall_state(providers) == ProviderState.NOT_INSTALLED

    def test_empty_list(self):
        assert _overall_state([]) == ProviderState.NOT_INSTALLED


class TestPickPrimary:
    def test_prefers_ready_over_off(self):
        providers = [
            _mk("LM Studio", ProviderState.INSTALLED_OFF),
            _mk("Ollama", ProviderState.READY),
        ]
        primary = _pick_primary(providers)
        assert primary is not None
        assert primary.name == "Ollama"

    def test_prefers_ollama_when_both_ready(self):
        providers = [
            _mk("LM Studio", ProviderState.READY),
            _mk("Ollama", ProviderState.READY),
        ]
        primary = _pick_primary(providers)
        assert primary is not None
        assert primary.name == "Ollama"

    def test_prefers_ollama_off_over_lmstudio_off(self):
        providers = [
            _mk("LM Studio", ProviderState.INSTALLED_OFF),
            _mk("Ollama", ProviderState.INSTALLED_OFF),
        ]
        primary = _pick_primary(providers)
        assert primary is not None
        assert primary.name == "Ollama"

    def test_empty_returns_none(self):
        assert _pick_primary([]) is None
