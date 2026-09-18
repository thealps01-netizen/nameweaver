"""Tests for provider/engine classification and installed-name matching."""

from models import (
    LlmModel,
    UseCase,
    is_chat_model,
    is_engine_compatible,
    is_official_provider,
    is_reupload,
    is_trusted_source,
    match_installed_ids,
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


def test_installed_match_rejects_distinct_variant():
    # A different fine-tune of the same size must NOT be treated as installed.
    assert not name_matches_installed("gemma-2-2b-jpn-it", ["gemma2:2b"])
    assert name_matches_installed("gemma-2-2b-jpn-it", ["google/gemma-2-2b-jpn-it"])
    # Vision vs non-vision, and version 3.1 vs 3, stay distinct.
    assert not name_matches_installed("Qwen2.5-VL-3B", ["qwen2.5:3b"])
    assert not name_matches_installed("Llama-3.1-8B", ["llama3:8b"])


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


def test_trusted_first_party_source():
    m = LlmModel(name="Qwen2.5-7B-Instruct", provider="Qwen")
    assert is_trusted_source(m)
    assert not is_reupload(m)


def test_community_reupload_is_untrusted():
    m = LlmModel(
        name="Qwen2.5-7B-Instruct-GGUF",
        provider="bartowski",
        base_model="Qwen/Qwen2.5-7B-Instruct",
    )
    assert is_reupload(m)
    assert not is_trusted_source(m)


def test_trusted_org_quantizing_own_model_stays_trusted():
    m = LlmModel(name="X", provider="Qwen", base_model="Qwen/X-base")
    assert not is_reupload(m)
    assert is_trusted_source(m)


def test_params_b_unit_parsing():
    # Millions and thousands must not be read as billions (SmolLM-135M bug).
    assert abs(LlmModel(name="x", parameter_count="135M").params_b() - 0.135) < 1e-6
    assert abs(LlmModel(name="x", parameter_count="500M").params_b() - 0.5) < 1e-6
    assert abs(LlmModel(name="x", parameter_count="83K").params_b() - 8.3e-5) < 1e-9
    assert LlmModel(name="x", parameter_count="7B").params_b() == 7.0
    assert LlmModel(name="x", parameter_count="8x7B").params_b() == 56.0


def test_size_class_buckets():
    from models import size_class

    assert size_class(0.5)[1] == "tiny"
    assert size_class(3)[1] == "small"
    assert size_class(8)[1] == "medium"
    assert size_class(20)[1] == "large"
    assert size_class(50)[1] == "xl"
    assert size_class(180)[1] == "huge"
    assert size_class(0)[1] == "unknown"


def test_pc_comfort_reads():
    from scoring import FitLevel, ModelFit, RunMode, pc_comfort

    effortless = ModelFit(
        model=None,
        fit_level=FitLevel.PERFECT,
        run_mode=RunMode.GPU,
        utilization_pct=15,
        estimated_tps=1600,
    )
    assert pc_comfort(effortless)[1] == "effortless"

    too_tight = ModelFit(model=None, fit_level=FitLevel.TOO_TIGHT)
    assert pc_comfort(too_tight)[1] == "too_much"

    offload = ModelFit(
        model=None,
        fit_level=FitLevel.GOOD,
        run_mode=RunMode.CPU_OFFLOAD,
        utilization_pct=90,
        estimated_tps=8,
    )
    assert pc_comfort(offload)[1] == "heavy"


def test_runnability_traffic_light():
    from scoring import FitLevel, ModelFit, RunMode, runnability

    green = ModelFit(
        model=LlmModel(name="m", format="gguf"), fit_level=FitLevel.GOOD, run_mode=RunMode.GPU
    )
    assert runnability(green)[1] == "green"

    yellow = ModelFit(
        model=LlmModel(name="m", format="gguf"),
        fit_level=FitLevel.MARGINAL,
        run_mode=RunMode.CPU_OFFLOAD,
    )
    assert runnability(yellow)[1] == "yellow"

    bad_format = ModelFit(
        model=LlmModel(name="m", format="awq"), fit_level=FitLevel.GOOD, run_mode=RunMode.GPU
    )
    assert runnability(bad_format)[1] == "red"

    too_tight = ModelFit(model=LlmModel(name="m", format="gguf"), fit_level=FitLevel.TOO_TIGHT)
    assert runnability(too_tight)[1] == "red"


class TestTwoPassInstalledMatching:
    """`match_installed_ids`: exact matches claim an engine id, probable ones get
    what is left. This is what keeps a variant row from stealing the base model."""

    def test_a_distilled_catalog_name_gets_the_engine_id(self):
        matches = match_installed_ids(["DeepSeek-R1-Distill-Qwen-7B"], ["deepseek-r1:7b"])

        assert matches == {"DeepSeek-R1-Distill-Qwen-7B": ("deepseek-r1:7b", "likely")}

    def test_a_name_without_a_size_token_still_matches(self):
        # The real install this was written against (both are embedders).
        matches = match_installed_ids(["nomic-embed-text-v1.5"], ["nomic-embed-text:latest"])

        assert matches == {"nomic-embed-text-v1.5": ("nomic-embed-text:latest", "likely")}

    def test_exact_match_wins_the_id_over_a_variant(self):
        matches = match_installed_ids(["gemma-2-2b", "gemma-2-2b-jpn-it"], ["gemma2:2b"])

        assert matches == {"gemma-2-2b": ("gemma2:2b", "exact")}

    def test_an_older_release_does_not_steal_the_newer_row(self):
        matches = match_installed_ids(["Llama-3-8B", "Llama-3.1-8B"], ["llama3:8b"])

        assert matches == {"Llama-3-8B": ("llama3:8b", "exact")}

    def test_a_variant_keeps_the_id_when_it_has_no_exact_home(self):
        matches = match_installed_ids(["gemma-2-2b-jpn-it"], ["gemma2:2b"])

        assert matches == {"gemma-2-2b-jpn-it": ("gemma2:2b", "likely")}

    def test_probable_matching_still_requires_the_same_size(self):
        assert match_installed_ids(["Llama-3.1-8B"], ["llama3:70b"]) == {}

    def test_one_engine_id_is_claimed_once(self):
        matches = match_installed_ids(
            ["Mistral-7B-Instruct", "Mistral-7B-Instruct-v0.3"], ["mistral:7b-instruct"]
        )

        assert len(matches) == 1
        assert matches["Mistral-7B-Instruct"] == ("mistral:7b-instruct", "exact")

    def test_catalog_spellings_of_one_model_share_its_engine_id(self):
        """Hiding one of them would be the same false negative we are fixing."""
        matches = match_installed_ids(["Qwen2.5-7B", "Qwen2.5-7B-Instruct"], ["qwen2.5:7b"])

        assert matches["Qwen2.5-7B"] == ("qwen2.5:7b", "exact")
        assert matches["Qwen2.5-7B-Instruct"] == ("qwen2.5:7b", "exact")


class TestChatCapability:
    """Embedding models are runnable by an engine but cannot hold a chat."""

    def test_embedding_use_case_is_not_chattable(self):
        assert not is_chat_model(LlmModel(name="nomic-embed-text", use_case=UseCase.EMBEDDING))
        assert not is_chat_model(LlmModel(name="nomic-embed-text", use_case="embedding"))

    def test_an_embedding_capability_also_blocks_chat(self):
        assert not is_chat_model(LlmModel(name="bge-m3", capabilities=["embedding"]))

    def test_chat_models_stay_chattable(self):
        assert is_chat_model(LlmModel(name="Llama-3.1-8B", use_case="general"))
        assert is_chat_model(LlmModel(name="llama3.1:8b"))
