"""Tests for streaming inference runner."""

import json
from unittest.mock import patch

import runner


class _FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        pass


def _ollama_stream():
    return [
        json.dumps({"response": "Hello", "done": False}).encode(),
        json.dumps({"response": " world", "done": False}).encode(),
        json.dumps({"response": "!", "done": True}).encode(),
    ]


def _sse_stream(chunks):
    return [
        f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n".encode()
        for c in chunks
    ] + [b"data: [DONE]\n"]


class TestRunOllama:
    def test_streams_tokens(self):
        with patch("runner.urllib.request.urlopen", return_value=_FakeResponse(_ollama_stream())):
            tokens = list(runner.run_ollama("llama3", "hi"))
        assert "".join(tokens) == "Hello world!"

    def test_respects_cancel(self):
        with patch("runner.urllib.request.urlopen", return_value=_FakeResponse(_ollama_stream())):
            # Cancel immediately
            gen = runner.run_ollama("llama3", "hi", should_cancel=lambda: True)
            tokens = list(gen)
        assert tokens == []

    def test_connection_error_yields_message(self):
        with patch("runner.urllib.request.urlopen", side_effect=ConnectionError("refused")):
            tokens = list(runner.run_ollama("llama3", "hi"))
        joined = "".join(tokens)
        assert "error" in joined


class TestOpenAICompat:
    def test_lm_studio_streams(self):
        stream = _sse_stream(["Hel", "lo", " world"])
        with patch("runner.urllib.request.urlopen", return_value=_FakeResponse(stream)):
            tokens = list(runner.run_lm_studio("mistral", "hi"))
        assert "".join(tokens) == "Hello world"

    def test_sse_parse_done_terminates(self):
        stream = [
            f"data: {json.dumps({'choices': [{'delta': {'content': 'A'}}]})}\n".encode(),
            b"data: [DONE]\n",
            # Should NOT be yielded:
            f"data: {json.dumps({'choices': [{'delta': {'content': 'B'}}]})}\n".encode(),
        ]
        with patch("runner.urllib.request.urlopen", return_value=_FakeResponse(stream)):
            tokens = list(runner.run_lm_studio("x", "y"))
        assert "".join(tokens) == "A"

    def test_skips_malformed_lines(self):
        stream = [
            b"not a data line\n",
            b"\n",
            f"data: {json.dumps({'choices': [{'delta': {'content': 'Z'}}]})}\n".encode(),
            b"data: [DONE]\n",
        ]
        with patch("runner.urllib.request.urlopen", return_value=_FakeResponse(stream)):
            tokens = list(runner.run_lm_studio("x", "y"))
        assert "".join(tokens) == "Z"


class TestDispatch:
    def test_dispatch_ollama(self):
        with patch("runner.urllib.request.urlopen", return_value=_FakeResponse(_ollama_stream())):
            tokens = list(runner.run_model("m", "Ollama", "hi"))
        assert "Hello world!" in "".join(tokens)

    def test_dispatch_lm_studio(self):
        with patch("runner.urllib.request.urlopen", return_value=_FakeResponse(_sse_stream(["ok"]))):
            tokens = list(runner.run_model("m", "LM Studio", "hi"))
        assert "ok" in "".join(tokens)

    def test_dispatch_unknown(self):
        tokens = list(runner.run_model("m", "llama.cpp", "hi"))
        assert "not supported" in "".join(tokens)


class TestAvailableProvidersForModel:
    def test_matches_installed(self):
        class P:
            def __init__(self, name, available, installed):
                self.name = name
                self.available = available
                self.installed_models = installed

        providers = [
            P("Ollama", True, {"llama3:8b", "qwen2.5:7b"}),
            P("LM Studio", True, {"mistral-7b-instruct"}),
            P("Docker", False, {"llama3:8b"}),
        ]
        result = runner.available_providers_for_model("llama3", providers)
        assert "Ollama" in result
        assert "Docker" not in result  # Not available

    def test_empty_when_no_match(self):
        class P:
            def __init__(self):
                self.name = "Ollama"
                self.available = True
                self.installed_models = {"something-else"}

        assert runner.available_providers_for_model("llama3", [P()]) == []


class _FakeProvider:
    def __init__(self, name, models, available=True):
        self.name = name
        self.installed_models = set(models)
        self.available = available


def test_installed_model_ids_maps_catalog_to_engine_id():
    provs = [
        _FakeProvider("Ollama", {"llama3.1:8b", "gemma2:2b"}),
        _FakeProvider("LM Studio", {"google/gemma-2-2b-jpn-it"}),
    ]
    ids = runner.installed_model_ids("gemma-2-2b-jpn-it", provs)
    # The distinct jpn-it variant must NOT match Ollama's plain gemma2:2b.
    assert "Ollama" not in ids
    assert ids["LM Studio"] == "google/gemma-2-2b-jpn-it"


def test_installed_model_ids_matches_real_ollama_tag():
    provs = [_FakeProvider("Ollama", {"llama3.1:8b"})]
    ids = runner.installed_model_ids("Llama-3.1-8B-Instruct", provs)
    assert ids["Ollama"] == "llama3.1:8b"


def test_installed_model_ids_empty_when_no_match():
    provs = [_FakeProvider("Ollama", {"mistral:7b"})]
    assert runner.installed_model_ids("gemma-2-2b", provs) == {}
