"""Tests for provider/engine classification and installed-name matching."""

from models import (
    is_engine_compatible,
    is_official_provider,
    name_matches_installed,
    normalize_model_name,
)


def test_normalize_folds_separators_and_case():
    assert normalize_model_name("Llama-3.1-8B-Instruct") == "llama318binstruct"
    # Ollama-style name reduces to the same key.
    assert normalize_model_name("llama3.1:8b-instruct") == "llama318binstruct"


def test_normalize_drops_digest_suffix():
    assert normalize_model_name("mymodel@sha256:deadbeef") == "mymodel"


def test_installed_match_handles_naming_differences():
    # The regression behind "engine selection sometimes doesn't work".
    assert name_matches_installed("Llama-3.1-8B-Instruct", ["llama3.1:8b-instruct"])
    assert name_matches_installed("Qwen2.5-7B-Instruct", ["qwen2.5:7b-instruct-q4_K_M"])
    assert name_matches_installed("Gemma-2-9B-Instruct", ["gemma2:9b-instruct"])


def test_installed_match_rejects_unrelated():
    assert not name_matches_installed("Mistral-7B", ["llama3:8b"])
    assert not name_matches_installed("", ["llama3:8b"])


def test_official_provider_allowlist():
    for org in ("meta-llama", "Meta", "Qwen", "alibaba", "deepseek-ai", "google"):
        assert is_official_provider(org), org


def test_community_providers_not_official():
    for org in ("TheBloke", "bartowski", "unsloth", "lmstudio-community", "mradermacher"):
        assert not is_official_provider(org), org


def test_engine_compatibility_by_format():
    assert is_engine_compatible("gguf")
    assert is_engine_compatible("GGUF")
    assert is_engine_compatible("")  # unknown → treated as gguf-compatible
    assert not is_engine_compatible("awq")
    assert not is_engine_compatible("gptq")
