"""Tests for model definitions and loading."""

import json
import tempfile
from pathlib import Path

from models import LlmModel, UseCase, load_models, merge_models, QUANT_BPP


class TestLlmModel:
    def test_params_b_standard(self):
        m = LlmModel(name="test", parameter_count="7B")
        assert m.params_b() == 7.0

    def test_params_b_decimal(self):
        m = LlmModel(name="test", parameter_count="1.5B")
        assert m.params_b() == 1.5

    def test_params_b_large(self):
        m = LlmModel(name="test", parameter_count="70B")
        assert m.params_b() == 70.0

    def test_params_b_moe(self):
        m = LlmModel(name="test", parameter_count="8x7B")
        assert m.params_b() == 56.0

    def test_params_b_empty(self):
        m = LlmModel(name="test", parameter_count="")
        assert m.params_b() == 0.0

    def test_params_b_no_suffix(self):
        m = LlmModel(name="test", parameter_count="7")
        assert m.params_b() == 7.0

    def test_is_moe(self, moe_model):
        assert moe_model.is_moe() is True

    def test_not_moe(self, small_model):
        assert small_model.is_moe() is False

    def test_active_params_dense(self, small_model):
        assert small_model.active_params_b() == small_model.params_b()

    def test_active_params_moe(self, moe_model):
        active = moe_model.active_params_b()
        total = moe_model.params_b()
        assert active < total
        assert active > 0

    def test_estimate_disk_gb(self, small_model):
        disk = small_model.estimate_disk_gb("Q4_K_M")
        assert disk > 0
        # Q4_K_M = 0.5 BPP, 3B params => ~1.5 GB
        assert 1.0 <= disk <= 2.0

    def test_estimate_memory_gb(self, small_model):
        mem = small_model.estimate_memory_gb("Q4_K_M")
        assert mem > small_model.estimate_disk_gb("Q4_K_M")  # Should include overhead

    def test_best_quant_for_budget(self, small_model):
        result = small_model.best_quant_for_budget(10.0)
        assert result is not None
        quant, mem = result
        assert quant in QUANT_BPP
        assert mem <= 10.0

    def test_best_quant_too_small(self, large_model):
        result = large_model.best_quant_for_budget(1.0)
        assert result is None

    def test_get_use_case(self):
        m = LlmModel(name="test", use_case="coding")
        assert m.get_use_case() == UseCase.CODING

    def test_get_use_case_invalid(self):
        m = LlmModel(name="test", use_case="invalid")
        assert m.get_use_case() == UseCase.GENERAL


class TestLoadModels:
    def test_load_embedded(self):
        models = load_models()
        assert len(models) > 0
        assert all(isinstance(m, LlmModel) for m in models)

    def test_load_from_custom_path(self, tmp_path):
        data = [
            {"name": "Test-1B", "provider": "test", "parameter_count": "1B"},
            {"name": "Test-7B", "provider": "test", "parameter_count": "7B"},
        ]
        path = tmp_path / "models.json"
        path.write_text(json.dumps(data))
        models = load_models(path)
        assert len(models) == 2

    def test_load_missing_file(self, tmp_path):
        models = load_models(tmp_path / "nonexistent.json")
        assert models == []

    def test_load_corrupt_json(self, tmp_path):
        path = tmp_path / "models.json"
        path.write_text("{corrupt json!!!")
        models = load_models(path)
        assert models == []

    def test_load_skips_malformed(self, tmp_path):
        data = [
            {"name": "Good-1B", "parameter_count": "1B"},
            "not a dict",
            {"name": "Good-7B", "parameter_count": "7B"},
        ]
        path = tmp_path / "models.json"
        path.write_text(json.dumps(data))
        models = load_models(path)
        assert len(models) == 2


class TestMergeModels:
    def test_merge_empty_cache(self):
        embedded = [LlmModel(name="A", parameter_count="1B")]
        merged = merge_models(embedded, [])
        assert len(merged) == 1
        assert merged[0].name == "A"

    def test_merge_empty_embedded(self):
        cached = [LlmModel(name="B", parameter_count="2B")]
        merged = merge_models([], cached)
        assert len(merged) == 1
        assert merged[0].name == "B"

    def test_merge_deduplicates_by_name(self):
        embedded = [
            LlmModel(name="A", parameter_count="1B", provider="old"),
            LlmModel(name="B", parameter_count="7B"),
        ]
        cached = [
            LlmModel(name="A", parameter_count="1B", provider="new"),
            LlmModel(name="C", parameter_count="3B"),
        ]
        merged = merge_models(embedded, cached)
        assert len(merged) == 3
        names = {m.name for m in merged}
        assert names == {"A", "B", "C"}
        # Cache takes priority
        a = next(m for m in merged if m.name == "A")
        assert a.provider == "new"

    def test_merge_case_insensitive_dedup(self):
        embedded = [LlmModel(name="Llama", parameter_count="7B")]
        cached = [LlmModel(name="llama", parameter_count="7B", provider="hf")]
        merged = merge_models(embedded, cached)
        assert len(merged) == 1

    def test_merge_sorted(self):
        embedded = [
            LlmModel(name="Z-model", provider="zeta"),
            LlmModel(name="A-model", provider="alpha"),
        ]
        merged = merge_models(embedded, [])
        # Sorted by provider then name
        assert merged[0].provider == "alpha"
        assert merged[1].provider == "zeta"
