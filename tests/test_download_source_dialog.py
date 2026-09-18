"""Tests for the download chooser.

The flow this replaces was a chain of modal questions — trust warning, source
list, "Ollama is off", then the tag — where each answer was given before the next
question was visible. These tests pin the new single dialog: what it offers given
the engines, what it prefills, and what it refuses to let through.
"""

from __future__ import annotations

import pytest

from models import LlmModel
from providers import ProviderState, ProviderStatus
from widgets.download_dialog import DownloadSourceDialog


def _status(name: str, state: ProviderState) -> ProviderStatus:
    return ProviderStatus(name=name, available=state == ProviderState.READY, state=state)


def _model(**kwargs) -> LlmModel:
    defaults = {"name": "DeepSeek-R1-Distill-Qwen-7B", "provider": "deepseek-ai"}
    return LlmModel(**{**defaults, **kwargs})


def _dialog(qtbot, model=None, providers=()) -> DownloadSourceDialog:
    dialog = DownloadSourceDialog(
        model or _model(),
        list(providers),
        "dark",
    )
    qtbot.addWidget(dialog)
    return dialog


class TestOfferedSources:
    @pytest.mark.parametrize(
        "state, expected",
        [(ProviderState.READY, "ready"), (ProviderState.INSTALLED_OFF, "off")],
    )
    def test_an_installed_engine_is_offered_with_its_state(self, qtbot, state, expected):
        dialog = _dialog(qtbot, providers=[_status("Ollama", state)])
        assert dialog.available_sources() == ["ollama", "hf"]
        assert expected in dialog._radios["ollama"].text()

    def test_an_engine_that_is_not_installed_is_not_offered(self, qtbot):
        dialog = _dialog(qtbot, providers=[_status("Ollama", ProviderState.NOT_INSTALLED)])
        assert dialog.available_sources() == ["hf"]

    def test_a_ready_engine_comes_before_an_engine_that_is_off(self, qtbot):
        dialog = _dialog(
            qtbot,
            providers=[
                _status("Ollama", ProviderState.INSTALLED_OFF),
                _status("LM Studio", ProviderState.READY),
            ],
        )
        assert dialog.available_sources() == ["lmstudio", "ollama", "hf"]

    def test_the_first_offered_source_is_preselected(self, qtbot):
        dialog = _dialog(qtbot, providers=[_status("Ollama", ProviderState.READY)])
        assert dialog.selected_source() == "ollama"

    def test_an_off_engine_is_asked_to_start_but_huggingface_never_is(self, qtbot):
        dialog = _dialog(qtbot, providers=[_status("Ollama", ProviderState.INSTALLED_OFF)])
        assert dialog.wants_engine_start() is True

        dialog._radios["hf"].setChecked(True)
        assert dialog.wants_engine_start() is False


class TestOllamaTag:
    def test_the_tag_is_prefilled_with_the_library_spelling(self, qtbot):
        dialog = _dialog(qtbot, providers=[_status("Ollama", ProviderState.READY)])
        assert dialog.selected_id() == "deepseek-r1:7b"

    def test_the_prefill_is_editable(self, qtbot):
        dialog = _dialog(qtbot, providers=[_status("Ollama", ProviderState.READY)])
        assert dialog._tag_combo.isEditable() is True

    def test_an_emptied_tag_blocks_the_download(self, qtbot):
        dialog = _dialog(qtbot, providers=[_status("Ollama", ProviderState.READY)])
        assert dialog._download_btn.isEnabled() is True

        dialog._tag_combo.setCurrentText("   ")
        assert dialog.selected_id() == ""
        assert dialog._download_btn.isEnabled() is False


class TestTrustGate:
    def test_a_first_party_publisher_needs_no_checkbox(self, qtbot):
        dialog = _dialog(qtbot, providers=[_status("Ollama", ProviderState.READY)])
        assert dialog._check is None
        assert dialog._download_btn.isEnabled() is True

    def test_an_unverified_publisher_gates_the_download_behind_a_checkbox(self, qtbot):
        dialog = _dialog(qtbot, model=_model(provider="random-publisher"))
        assert dialog._check is not None
        assert dialog._download_btn.isEnabled() is False

        dialog._check.setChecked(True)
        assert dialog._download_btn.isEnabled() is True

    def test_a_reupload_names_what_it_was_uploaded_from(self, qtbot):
        dialog = _dialog(
            qtbot,
            model=_model(provider="random-publisher", base_model="deepseek-ai/DeepSeek-R1"),
        )
        texts = [
            child.text() for child in dialog.findChildren(type(dialog._detail)) if child.text()
        ]
        assert any("deepseek-ai/DeepSeek-R1" in text for text in texts)


class TestHuggingFaceSource:
    def test_no_id_is_asked_for_and_the_field_is_hidden(self, qtbot):
        dialog = _dialog(qtbot, providers=[_status("Ollama", ProviderState.READY)])
        dialog._radios["hf"].setChecked(True)

        assert dialog.selected_id() == ""
        assert dialog._tag_row.isHidden() is True

    def test_the_hint_says_the_repo_is_chosen_next(self, qtbot):
        dialog = _dialog(qtbot, providers=[_status("Ollama", ProviderState.READY)])
        dialog._radios["hf"].setChecked(True)
        assert "folder you choose" in dialog._detail.text()
