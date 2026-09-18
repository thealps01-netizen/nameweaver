"""Tests for the My Models view and the engine listings behind it.

The view is the one place Run lives, so these cover: rows come from the engines
(not the catalog), a model no catalog entry knows is still runnable, an embedding
model never is, and an engine that is off explains itself instead of looking
empty.
"""

from unittest.mock import patch

from providers import InstalledModel, ProviderState, ProviderStatus
from widgets.my_models import MyModelsView


def _status(name: str, state=ProviderState.READY, start_action: str = "") -> ProviderStatus:
    status = ProviderStatus(name=name, start_action=start_action)
    status.state = state
    status.available = state == ProviderState.READY
    return status


def _row(**overrides) -> dict:
    row = {
        "engine": "Ollama",
        "id": "gemma3:4b",
        "size_bytes": 3 * 1024**3,
        "parameters": "4B",
        "quantization": "Q4_K_M",
        "path": "",
        "catalog": "gemma-3-4b-it",
        "chat": True,
        "runnable": True,
    }
    row.update(overrides)
    return row


class TestMyModelsView:
    def test_a_row_comes_from_the_engine_and_can_run(self, qtbot):
        view = MyModelsView()
        qtbot.addWidget(view)

        view.set_rows([_row()], {"Ollama": _status("Ollama")})

        assert view.row_count() == 1
        assert view.cell_text(0, 1) == "Ollama"
        assert view.cell_text(0, 2) == "4B"
        assert view.cell_text(0, 4) == "Q4_K_M"
        assert view.cell_text(0, 5) == "gemma-3-4b-it"
        assert view.run_button(0).isEnabled() is True

    def test_run_sends_the_engines_own_id(self, qtbot):
        view = MyModelsView()
        qtbot.addWidget(view)
        view.set_rows(
            [_row(id="deepseek-r1:7b", catalog="DeepSeek-R1-Distill-Qwen-7B")],
            {"Ollama": _status("Ollama")},
        )
        seen = []
        view.run_requested.connect(lambda *args: seen.append(args))

        view.run_button(0).click()

        assert seen == [("Ollama", "deepseek-r1:7b", "DeepSeek-R1-Distill-Qwen-7B", True)]

    def test_a_model_outside_the_catalog_is_listed_and_runnable(self, qtbot):
        view = MyModelsView()
        qtbot.addWidget(view)

        view.set_rows(
            [_row(id="my-own-finetune:latest", catalog="", chat=None)],
            {"Ollama": _status("Ollama")},
        )

        assert view.cell_text(0, 0) == "my-own-finetune:latest"
        assert view.cell_text(0, 5) == "—"
        assert view.run_button(0).isEnabled() is True  # engine didn't object

    def test_an_embedding_model_cannot_be_run(self, qtbot):
        view = MyModelsView()
        qtbot.addWidget(view)

        view.set_rows(
            [_row(id="nomic-embed-text:latest", chat=False)], {"Ollama": _status("Ollama")}
        )

        assert view.cell_text(0, 6) == "no"
        assert view.run_button(0).isEnabled() is False
        assert "embedding" in view.run_button(0).toolTip().lower()

    def test_an_engine_that_is_off_says_so_and_offers_start(self, qtbot):
        view = MyModelsView()
        qtbot.addWidget(view)

        view.set_rows(
            [], {"LM Studio": _status("LM Studio", ProviderState.INSTALLED_OFF, "start_lmstudio")}
        )

        notices = [
            child.text()
            for child in view.findChildren(type(view._notice))
            if "LM Studio" in (child.text() or "")
        ]
        assert any("start it" in text for text in notices), notices

    def test_empty_state_points_at_the_catalog(self, qtbot):
        view = MyModelsView()
        qtbot.addWidget(view)

        view.set_rows([], {"Ollama": _status("Ollama")})

        assert view.row_count() == 0
        assert "Model Catalog" in view._empty.text()

    def test_select_model_finds_the_catalog_row(self, qtbot):
        view = MyModelsView()
        qtbot.addWidget(view)
        view.set_rows([_row()], {"Ollama": _status("Ollama")})

        assert view.select_model("gemma-3-4b-it") is True
        assert view.select_model("nothing-like-this") is False


class TestEngineListings:
    """providers.list_installed_models — the engines' own answers, mocked."""

    def test_ollama_rows_carry_size_params_quant_and_capabilities(self):
        payload = {
            "models": [
                {
                    "name": "nomic-embed-text:latest",
                    "size": 274302450,
                    "details": {"parameter_size": "137M", "quantization_level": "F16"},
                    "capabilities": ["embedding"],
                }
            ]
        }
        with patch("providers._http_get_json", return_value=payload):
            rows = [
                r for r in __import__("providers").list_installed_models() if r.engine == "Ollama"
            ]

        assert len(rows) == 1
        row = rows[0]
        assert row.id == "nomic-embed-text:latest"
        assert row.size_bytes == 274302450
        assert row.parameters == "137M"
        assert row.quantization == "F16"
        assert row.reported_by_engine is True
        assert row.engine_reports_no_chat is True

    def test_a_chat_model_is_not_reported_as_an_embedder(self):
        payload = {
            "models": [
                {"name": "gemma3:4b", "capabilities": ["completion", "tools"], "details": {}}
            ]
        }
        with patch("providers._http_get_json", return_value=payload):
            rows = [
                r for r in __import__("providers").list_installed_models() if r.engine == "Ollama"
            ]

        assert rows[0].engine_reports_no_chat is False

    def test_lmstudio_with_the_server_off_lists_the_folder(self, tmp_path, monkeypatch):
        (tmp_path / "org" / "model").mkdir(parents=True)
        model_file = tmp_path / "org" / "model" / "Model-Q4_K_M.gguf"
        model_file.write_bytes(b"x" * 1024)

        monkeypatch.setattr("providers._lmstudio_models_dir", lambda: tmp_path)
        with patch("providers._http_get_json", return_value=None):
            rows = [
                r
                for r in __import__("providers").list_installed_models()
                if r.engine == "LM Studio"
            ]

        assert len(rows) == 1
        assert rows[0].id == "Model-Q4_K_M"
        assert rows[0].reported_by_engine is False
        assert rows[0].size_bytes == 1024

    def test_lmstudio_with_the_server_on_uses_the_servers_ids(self, tmp_path, monkeypatch):
        (tmp_path / "org").mkdir()
        (tmp_path / "org" / "gemma-3-4b.gguf").write_bytes(b"y" * 2048)
        monkeypatch.setattr("providers._lmstudio_models_dir", lambda: tmp_path)

        payload = {"data": [{"id": "org/gemma-3-4b"}]}
        with patch("providers._http_get_json", return_value=payload):
            rows = [
                r
                for r in __import__("providers").list_installed_models()
                if r.engine == "LM Studio"
            ]

        assert [r.id for r in rows] == ["org/gemma-3-4b"]
        assert rows[0].reported_by_engine is True

    def test_installed_model_knows_when_an_engine_says_embedding_only(self):
        assert InstalledModel(
            engine="Ollama", id="x", capabilities=("embedding",)
        ).engine_reports_no_chat
        assert not InstalledModel(
            engine="Ollama", id="x", capabilities=("completion", "tools")
        ).engine_reports_no_chat
        assert not InstalledModel(engine="Ollama", id="x").engine_reports_no_chat


def test_the_run_column_fits_its_buttons(qtbot):
    """The Run column holds widgets, which the header cannot measure — leaving it
    to ResizeToContents elided the button down to "…" as soon as the theme's
    stylesheet changed the font. The width has to come from the buttons."""
    view = MyModelsView("dark")
    qtbot.addWidget(view)
    view.set_rows([_row()], {"Ollama": _status("Ollama")})
    view.resize(1200, 300)
    view.show()

    button = view._table.cellWidget(0, 7)

    assert button is not None
    assert view._table.columnWidth(7) >= button.sizeHint().width()
    assert view._table.horizontalHeader().sectionResizeMode(7).name == "Fixed"


def test_the_run_column_grows_with_the_button(qtbot):
    """Whatever the font does to the hint, the column follows it."""
    view = MyModelsView("dark")
    qtbot.addWidget(view)
    view.set_rows([_row()], {"Ollama": _status("Ollama")})
    view.resize(1200, 300)
    view.show()
    before = view._table.columnWidth(7)

    view.setStyleSheet("QPushButton { padding: 4px 24px; font-size: 15px; }")
    view.set_theme("dark")  # re-renders the rows, which re-measures the column

    assert view._table.columnWidth(7) >= before
    assert view._table.columnWidth(7) >= view._table.cellWidget(0, 7).sizeHint().width()
