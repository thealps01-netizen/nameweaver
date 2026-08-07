"""Tests for HuggingFace API client and conversion helpers."""

import json
from unittest.mock import patch

from hf_api import (
    HuggingFaceAPI,
    estimate_memory_gb,
    extract_param_count,
    infer_capabilities,
    infer_ctx_length,
    infer_use_case,
)


class TestExtractParamCount:
    def test_simple_7b(self):
        assert extract_param_count("Llama-3.1-7B-Instruct") == "7B"

    def test_decimal(self):
        assert extract_param_count("Qwen2.5-1.5B") == "1.5B"

    def test_moe(self):
        assert extract_param_count("Mixtral-8x7B-v0.1") == "8x7B"

    def test_million(self):
        assert extract_param_count("gpt2-125M") == "125M"

    def test_none(self):
        assert extract_param_count("some-random-model") == ""

    def test_from_tags(self):
        assert extract_param_count("unknown", ["3B", "instruct"]) == "3B"


class TestInferUseCase:
    def test_coding(self):
        assert infer_use_case("qwen2.5-coder-7b") == "coding"

    def test_vision(self):
        assert infer_use_case("Llama-3.2-11B-Vision") == "multimodal"

    def test_reasoning(self):
        assert infer_use_case("DeepSeek-R1-Distill-7B") == "reasoning"

    def test_embedding(self):
        assert infer_use_case("bge-base-en-v1.5") == "embedding"

    def test_chat_from_tags(self):
        assert infer_use_case("random", ["text-generation", "chat"]) == "chat"

    def test_default_general(self):
        assert infer_use_case("Llama-3-8B") == "general"


class TestInferCapabilities:
    def test_vision(self):
        caps = infer_capabilities(["vision", "text-generation"])
        assert "vision" in caps

    def test_image_text(self):
        caps = infer_capabilities(["image-text-to-text"])
        assert "vision" in caps

    def test_tool_use(self):
        caps = infer_capabilities(["function-calling"])
        assert "tool_use" in caps

    def test_empty(self):
        assert infer_capabilities([]) == []


class TestInferCtxLength:
    def test_llama3_family(self):
        assert infer_ctx_length("Meta-Llama-3.1-8B-Instruct") == 131072

    def test_from_config(self):
        cfg = {"max_position_embeddings": 16384}
        assert infer_ctx_length("anything", cfg) == 16384

    def test_k_pattern(self):
        assert infer_ctx_length("something-128k-chat") == 131072

    def test_default_4k(self):
        assert infer_ctx_length("obscure-model") == 4096


class TestEstimateMemoryGb:
    def test_7b_q4(self):
        ram, vram = estimate_memory_gb(7.0, "Q4_K_M")
        assert vram > 3.0
        assert ram > vram

    def test_70b_q4(self):
        _ram, vram = estimate_memory_gb(70.0, "Q4_K_M")
        assert vram > 30.0


class TestHuggingFaceAPIMocked:
    @patch("hf_api._http_json")
    def test_search_returns_list(self, mock_http):
        mock_http.return_value = [{"modelId": "org/model", "tags": ["7B"]}]
        api = HuggingFaceAPI()
        result = api.search_models("llama")
        assert len(result) == 1
        assert result[0]["modelId"] == "org/model"

    @patch("hf_api._http_json")
    def test_search_invalid_response(self, mock_http):
        mock_http.return_value = None
        api = HuggingFaceAPI()
        assert api.search_models("x") == []

    @patch("hf_api._http_json")
    def test_trending(self, mock_http):
        mock_http.return_value = [{"modelId": "a/b", "tags": []}]
        api = HuggingFaceAPI()
        assert len(api.fetch_trending(limit=10)) == 1

    @patch("hf_api._http_json")
    def test_convert_to_llm_model(self, mock_http):
        api = HuggingFaceAPI()
        entry = {
            "modelId": "meta-llama/Meta-Llama-3.1-8B-Instruct",
            "tags": ["text-generation", "instruct", "license:llama3.1"],
            "createdAt": "2024-07-23T18:00:00.000Z",
        }
        model = api.convert_to_llm_model(entry)
        assert model is not None
        assert model.name == "Meta-Llama-3.1-8B-Instruct"
        assert model.provider == "meta-llama"
        assert model.parameter_count == "8B"
        assert model.use_case == "chat"
        assert model.license == "llama3.1"
        assert model.ctx_length == 131072
        assert model.vram_gb > 0

    def test_convert_skips_no_param(self):
        api = HuggingFaceAPI()
        entry = {"modelId": "foo/bar", "tags": []}
        assert api.convert_to_llm_model(entry) is None

    def test_convert_skips_no_repo(self):
        api = HuggingFaceAPI()
        entry = {"tags": ["7B"]}
        assert api.convert_to_llm_model(entry) is None

    def test_convert_moe_from_name(self):
        api = HuggingFaceAPI()
        entry = {
            "modelId": "mistralai/Mixtral-8x7B-Instruct-v0.1",
            "tags": ["text-generation"],
        }
        model = api.convert_to_llm_model(entry)
        assert model is not None
        assert model.parameter_count == "8x7B"
        assert model.expert_count == 8

    def test_convert_with_config(self):
        api = HuggingFaceAPI()
        entry = {"modelId": "x/Model-7B", "tags": []}
        config = {
            "num_hidden_layers": 32,
            "num_attention_heads": 32,
            "hidden_size": 4096,
            "vocab_size": 32000,
            "max_position_embeddings": 8192,
        }
        model = api.convert_to_llm_model(entry, config)
        assert model is not None
        assert model.n_layers == 32
        assert model.ctx_length == 8192


class TestCacheRoundtrip:
    def test_save_and_read_meta(self, tmp_path, monkeypatch):
        import hf_api

        monkeypatch.setattr(hf_api, "cache_path", lambda: tmp_path / "cache.json")

        from models import LlmModel

        models = [LlmModel(name="A", parameter_count="1B")]
        hf_api.save_cache(models)

        meta = hf_api.read_cache_meta()
        assert meta["version"] == hf_api.CACHE_VERSION
        assert meta["count"] == 1
        assert "updated_at" in meta

    def test_read_cache_meta_missing(self, tmp_path, monkeypatch):
        import hf_api

        monkeypatch.setattr(hf_api, "cache_path", lambda: tmp_path / "absent.json")
        assert hf_api.read_cache_meta() == {}

    def test_read_cache_meta_corrupt(self, tmp_path, monkeypatch):
        import hf_api

        p = tmp_path / "cache.json"
        p.write_text("{not json")
        monkeypatch.setattr(hf_api, "cache_path", lambda: p)
        assert hf_api.read_cache_meta() == {}
