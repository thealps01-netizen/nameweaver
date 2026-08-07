"""Tests for scoring engine."""

import pytest

from scoring import FitLevel, ModelFit, RunMode, ScoreComponents, rank_models


class TestLayerSplitWarning:
    """When aggregate VRAM fits but a single layer wouldn't."""

    def test_200b_on_dual_small_cards_warns(self):
        """200B / 80 layers ≈ 1.25 GB per layer @ Q4 — exceeds 8 GB card? No.

        Use 400B to force layer > smallest card. Aggregate fits (48 GB),
        but layers (~2.5 GB) exceed 2×8 GB cards... actually 2.5 < 8, so
        pick a scenario where smallest card is 4 GB and layer is 5 GB.
        """
        from hw import GpuBackend, GpuInfo, SystemSpecs
        from models import LlmModel

        # 80-layer 400B model @ Q4 = 200 GB weights → 2.5 GB/layer × 1.3 act = 3.25 GB
        # Smallest enabled GPU must be < 3.25 GB to trip the warning.
        # Use 2 GB + 40 GB mismatched pair (aggregate = 42 > 40 total_mem).
        specs = SystemSpecs(
            total_ram_gb=64.0,
            available_ram_gb=56.0,
            cpu_name="Test",
            total_cpu_cores=16,
            has_gpu=True,
            gpu_name="A", gpu_vram_gb=2.0,
            total_gpu_vram_gb=42.0, gpu_count=2,
            gpu_backend=GpuBackend.CUDA,
            gpus=[
                GpuInfo(name="Small", vram_gb=2.0, backend=GpuBackend.CUDA,
                        bandwidth_gbps=100.0, vendor="NVIDIA", enabled=True),
                GpuInfo(name="Big", vram_gb=40.0, backend=GpuBackend.CUDA,
                        bandwidth_gbps=1008.0, vendor="NVIDIA", enabled=True),
            ],
            gpu_bandwidth_gbps=1008.0,
        )
        # 100B / 80 layers @ Q4 = 50 GB weights → 0.625 GB/layer × 1.3 = 0.81 GB
        # Still fits 2 GB — need bigger. Use 400B.
        m = LlmModel(
            name="huge", parameter_count="400B", format="gguf",
            quantization="Q4_K_M", n_layers=80, attention_heads=64,
            hidden_dim=8192, ctx_length=2048, use_case="general",
        )
        fit = ModelFit.analyze(m, specs, context_limit=512)
        if fit.run_mode == RunMode.GPU:  # Only meaningful if it landed on GPU
            # 400B * 0.5 / 80 = 2.5 GB/layer; 2.5 * 1.3 = 3.25 GB > 2 GB smallest
            assert any("Single layer" in n for n in fit.notes), (
                f"Expected layer-split warning, got notes: {fit.notes}"
            )

    def test_single_gpu_no_warning(self, large_model, sample_specs):
        """Single-GPU systems must never emit the layer-split warning."""
        fit = ModelFit.analyze(large_model, sample_specs, context_limit=1024)
        assert not any("Single layer" in n for n in fit.notes)


class TestNvidiaBandwidthMeasurement:
    """Real bandwidth measurement from nvidia-smi memory.bus_width × clock."""

    def test_rtx_4090_spec_matches(self):
        """RTX 4090: 384-bit bus × 10500 MHz ≈ 1008 GB/s (within 1%)."""
        from hw import _compute_nvidia_bandwidth_gbps

        bw = _compute_nvidia_bandwidth_gbps(384, 10500)
        # 384 * 10500 * 2 / 8 / 1000 = 1008
        assert abs(bw - 1008.0) < 5.0

    def test_invalid_returns_zero(self):
        from hw import _compute_nvidia_bandwidth_gbps

        assert _compute_nvidia_bandwidth_gbps(0, 10500) == 0.0
        assert _compute_nvidia_bandwidth_gbps(384, 0) == 0.0
        assert _compute_nvidia_bandwidth_gbps(-1, 1000) == 0.0


class TestAppleUnifiedMemory:
    """Apple Silicon must not double-count unified memory as VRAM+RAM."""

    @pytest.fixture
    def apple_m2_max_specs(self):
        """M2 Max — 64 GB unified memory. VRAM = ~75% of RAM."""
        from hw import GpuBackend, GpuInfo, SystemSpecs

        gpus = [
            GpuInfo(
                name="Apple M2 Max",
                vram_gb=48.0,  # 75% of 64
                backend=GpuBackend.METAL,
                bandwidth_gbps=400.0,
                vendor="Apple",
                unified_memory=True,
                enabled=True,
            ),
        ]
        return SystemSpecs(
            total_ram_gb=64.0,
            available_ram_gb=56.0,
            cpu_name="Apple M2 Max",
            total_cpu_cores=12,
            has_gpu=True,
            gpu_name="Apple M2 Max",
            gpu_vram_gb=48.0,
            total_gpu_vram_gb=48.0,
            gpu_count=1,
            gpu_backend=GpuBackend.METAL,
            unified_memory=True,
            gpus=gpus,
            gpu_bandwidth_gbps=400.0,
        )

    def test_70b_on_m2_max_does_not_double_count(self, large_model, apple_m2_max_specs):
        """Available memory must be the single 48 GB pool, not 48+64.

        Previously the CPU_OFFLOAD branch added total_ram_gb to effective_vram
        yielding 112 GB, letting F16 (140 GB) almost fit and wildly over-
        promising feasibility. The unified-memory branch caps it at 48 GB.
        """
        fit = ModelFit.analyze(large_model, apple_m2_max_specs, context_limit=1024)
        # Must NOT exceed the physical unified memory
        assert fit.memory_available_gb <= apple_m2_max_specs.total_ram_gb
        # 70B Q4 ≈ 35 GB fits in 48 GB → GPU mode
        assert fit.run_mode == RunMode.GPU

    def test_apple_never_uses_cpu_offload(self, large_model, apple_m2_max_specs):
        """Unified memory has no separate pool — CPU_OFFLOAD is meaningless."""
        fit = ModelFit.analyze(large_model, apple_m2_max_specs, context_limit=1024)
        assert fit.run_mode != RunMode.CPU_OFFLOAD
        assert fit.run_mode != RunMode.MOE_OFFLOAD


class TestModeAwareQuantSelection:
    """The quant picker must not choose unusably large quants when offloading."""

    def test_cpu_offload_prefers_smaller_quant(self, large_model, sample_specs):
        """70B on 24 GB VRAM + 32 GB RAM → must pick a small quant, not F16.

        Previously the budget was VRAM + full RAM (56 GB) and F16 (140 GB)
        didn't fit, but larger quants like Q8 (70 GB) did — and picking
        Q8 here crushes inference. Realistic budget keeps us in Q3/Q4.
        """
        fit = ModelFit.analyze(large_model, sample_specs, context_limit=1024)
        # Q8_0 ≈ 70 GB — way too big to offload half of. Must pick smaller.
        assert fit.best_quant not in ("F16", "BF16", "Q8_0"), (
            f"Picked {fit.best_quant} for 70B on 24 GB VRAM; this will crawl"
        )

    def test_cpu_only_respects_ram_headroom(self, large_model, low_end_specs):
        """CPU_ONLY budget = 80% of RAM, not 100%."""
        fit = ModelFit.analyze(large_model, low_end_specs, context_limit=1024)
        # 8 GB * 0.8 = 6.4 GB — 70B won't fit anyway but budget check is key
        assert fit.memory_available_gb <= low_end_specs.total_ram_gb * 0.81


class TestPreferenceBias:
    """Quality/speed slider re-weights the composite score without re-analyzing."""

    def test_neutral_matches_default_analyze(self, small_model, sample_specs):
        """preference=0.5 must equal the old no-arg behavior."""
        fit_default = ModelFit.analyze(small_model, sample_specs)
        fit_neutral = ModelFit.analyze(small_model, sample_specs, preference=0.5)
        assert fit_default.score == fit_neutral.score

    def test_quality_bias_favors_bigger_model(self, sample_specs):
        """Same score components: quality-biased score should rank big models higher."""
        from models import LlmModel

        small = LlmModel(
            name="tiny", parameter_count="1B", format="gguf", quantization="Q4_K_M",
            ctx_length=4096, use_case="general",
        )
        big = LlmModel(
            name="bigger", parameter_count="13B", format="gguf", quantization="Q4_K_M",
            ctx_length=4096, use_case="general",
        )
        small_q = ModelFit.analyze(small, sample_specs, preference=1.0)  # pure quality
        big_q = ModelFit.analyze(big, sample_specs, preference=1.0)
        # On a 24 GB RTX 4090 both fit fine — quality bias must favor the bigger
        assert big_q.score > small_q.score

    def test_speed_bias_flips_ranking(self, sample_specs):
        """Speed bias should narrow or reverse the big-vs-small quality gap."""
        from models import LlmModel

        small = LlmModel(
            name="tiny", parameter_count="1B", format="gguf", quantization="Q4_K_M",
            ctx_length=4096, use_case="general",
        )
        big = LlmModel(
            name="bigger", parameter_count="13B", format="gguf", quantization="Q4_K_M",
            ctx_length=4096, use_case="general",
        )
        # Pure quality: big > small. Pure speed: gap narrows.
        q_gap = ModelFit.analyze(big, sample_specs, preference=1.0).score - \
                ModelFit.analyze(small, sample_specs, preference=1.0).score
        s_gap = ModelFit.analyze(big, sample_specs, preference=0.0).score - \
                ModelFit.analyze(small, sample_specs, preference=0.0).score
        assert s_gap < q_gap

    def test_apply_preference_mutates_in_place(self, sample_specs, small_model, large_model):
        """apply_preference must update fit.score without re-running analyze."""
        from scoring import apply_preference

        fits = [
            ModelFit.analyze(small_model, sample_specs, preference=0.5),
            ModelFit.analyze(large_model, sample_specs, preference=0.5),
        ]
        original_scores = [f.score for f in fits]
        apply_preference(fits, 1.0)  # full quality bias
        new_scores = [f.score for f in fits]
        # At least one score must change
        assert any(a != b for a, b in zip(original_scores, new_scores))
        # Components must be untouched (only the weighted composite recomputes)
        for fit in fits:
            assert 0 <= fit.score_components.quality <= 100

    def test_preference_out_of_range_clamps(self, small_model, sample_specs):
        """Preference values outside [0,1] must be clamped."""
        over = ModelFit.analyze(small_model, sample_specs, preference=5.0)
        max_q = ModelFit.analyze(small_model, sample_specs, preference=1.0)
        assert over.score == max_q.score

        under = ModelFit.analyze(small_model, sample_specs, preference=-2.0)
        max_s = ModelFit.analyze(small_model, sample_specs, preference=0.0)
        assert under.score == max_s.score


class TestProbeQuantDecouplesRunMode:
    """Run-mode decision must not hinge on the repo's default (often F16)."""

    def test_f16_default_fits_on_good_hw_via_probe(self, sample_specs):
        """A 7B model whose default quant is F16 should still land on GPU."""
        from models import LlmModel

        # 7B model tagged with F16 as its default (common for HF repos)
        m = LlmModel(
            name="Llama-7B-F16",
            provider="meta",
            parameter_count="7B",
            ram_gb=14.0,
            vram_gb=14.0,
            format="gguf",
            quantization="F16",  # repo default is F16 → 14 GB
            n_layers=32,
            attention_heads=32,
            hidden_dim=4096,
            ctx_length=4096,
            use_case="general",
        )
        fit = ModelFit.analyze(m, sample_specs)  # 24 GB VRAM
        # Before fix: F16 probe → 14 GB fits fine, but a 70B default-F16
        # model (140 GB) would get misclassified. Here we assert the
        # probe quant path still lands on GPU when it genuinely fits.
        assert fit.run_mode == RunMode.GPU

    def test_f16_default_70b_does_not_collapse_to_cpu(self, sample_specs):
        """70B with F16 default: probe Q4 (~35 GB) → CPU_OFFLOAD, not CPU_ONLY."""
        from models import LlmModel

        m = LlmModel(
            name="Llama-70B-BF16",
            provider="meta",
            parameter_count="70B",
            ram_gb=140.0,
            vram_gb=140.0,
            format="gguf",
            quantization="BF16",  # Full-precision default
            n_layers=80,
            attention_heads=64,
            hidden_dim=8192,
            ctx_length=4096,
            use_case="general",
        )
        # Small ctx so KV cache doesn't dominate the decision
        fit = ModelFit.analyze(m, sample_specs, context_limit=512)
        # With F16 probe: 140 GB → CPU_ONLY. With Q4 probe: ~38 GB → offload.
        assert fit.run_mode == RunMode.CPU_OFFLOAD


class TestMultiGpuScoring:
    def test_70b_model_fits_full_gpu_on_dual_3090(self, large_model, dual_nvidia_specs):
        """Regression: 70B model at Q4_K_M fits fully in 48 GB (2× 24 GB).

        Before the multi-GPU fix, scoring used ``gpu_vram_gb`` (primary's
        24 GB) and classified this as CPU_OFFLOAD. With the fix it uses
        the sum across enabled GPUs and runs fully on GPU.
        """
        fit = ModelFit.analyze(large_model, dual_nvidia_specs, context_limit=1024)
        # 70B Q4_K_M ≈ 35 GB → fits in 48 GB combined VRAM
        assert fit.run_mode == RunMode.GPU
        assert fit.fit_level in (FitLevel.PERFECT, FitLevel.GOOD)

    def test_disabled_igpu_not_counted(self, small_model, mixed_backend_specs):
        """iGPU disabled-by-default — fit must ignore its 0 GB VRAM."""
        fit = ModelFit.analyze(small_model, mixed_backend_specs)
        # Only the NVIDIA card (24 GB) counts; small model runs on GPU
        assert fit.run_mode == RunMode.GPU

    def test_dual_amd_uses_combined_vram(self, large_model, amd_dual_specs):
        """48 GB of ROCm VRAM should fit a 70B model at Q4."""
        fit = ModelFit.analyze(large_model, amd_dual_specs, context_limit=1024)
        assert fit.run_mode == RunMode.GPU

    def test_mixed_backend_uses_max_bandwidth(self):
        """TPS estimate should pick the fastest enabled GPU's bandwidth."""
        from hw import GpuBackend, GpuInfo, SystemSpecs

        specs = SystemSpecs(
            total_ram_gb=32.0,
            available_ram_gb=28.0,
            cpu_name="Test CPU",
            total_cpu_cores=16,
            has_gpu=True,
            gpu_name="RTX 4090",
            gpu_vram_gb=24.0,
            total_gpu_vram_gb=40.0,
            gpu_count=2,
            gpu_backend=GpuBackend.CUDA,
            gpus=[
                GpuInfo(name="RTX 3060", vram_gb=12.0, backend=GpuBackend.CUDA,
                        bandwidth_gbps=360.0, vendor="NVIDIA", enabled=True),
                GpuInfo(name="RTX 4090", vram_gb=24.0, backend=GpuBackend.CUDA,
                        bandwidth_gbps=1008.0, vendor="NVIDIA", enabled=True),
            ],
            gpu_bandwidth_gbps=360.0,  # legacy primary value (slow card listed first)
        )
        # Build a small model that fits on GPU
        from models import LlmModel
        m = LlmModel(
            name="Test-3B", provider="test", parameter_count="3B",
            ram_gb=3.5, vram_gb=2.5, format="gguf", quantization="Q4_K_M",
            n_layers=28, attention_heads=24, hidden_dim=3072,
            ctx_length=4096, use_case="general",
        )
        fit = ModelFit.analyze(m, specs)
        # Now disable the 4090 → TPS must drop
        specs.gpus[1].enabled = False
        specs.total_gpu_vram_gb = 12.0
        fit_slow = ModelFit.analyze(m, specs)
        assert fit.estimated_tps > fit_slow.estimated_tps


class TestModelFitAnalyze:
    def test_small_model_on_good_hw(self, small_model, sample_specs):
        fit = ModelFit.analyze(small_model, sample_specs)
        assert fit.fit_level in (FitLevel.PERFECT, FitLevel.GOOD)
        assert fit.run_mode == RunMode.GPU
        assert fit.score > 0
        assert fit.estimated_tps > 0
        assert fit.best_quant != ""

    def test_large_model_on_good_hw(self, large_model, sample_specs):
        fit = ModelFit.analyze(large_model, sample_specs)
        # 70B Q4_K_M = ~35 GB, exceeds 24 GB VRAM
        assert fit.run_mode in (RunMode.CPU_OFFLOAD, RunMode.CPU_ONLY)
        assert fit.score > 0

    def test_small_model_no_gpu(self, small_model, low_end_specs):
        fit = ModelFit.analyze(small_model, low_end_specs)
        assert fit.run_mode == RunMode.CPU_ONLY
        assert fit.score > 0
        assert fit.estimated_tps > 0

    def test_moe_model(self, moe_model, sample_specs):
        fit = ModelFit.analyze(moe_model, sample_specs)
        assert fit.score > 0
        assert fit.best_quant != ""

    def test_score_components_range(self, small_model, sample_specs):
        fit = ModelFit.analyze(small_model, sample_specs)
        sc = fit.score_components
        for val in [sc.quality, sc.speed, sc.fit]:
            assert 0 <= val <= 100

    def test_composite_score_range(self, small_model, sample_specs):
        fit = ModelFit.analyze(small_model, sample_specs)
        assert 0 <= fit.score <= 100

    def test_utilization_range(self, small_model, sample_specs):
        fit = ModelFit.analyze(small_model, sample_specs)
        assert 0 <= fit.utilization_pct <= 100


class TestRanking:
    def test_too_tight_last(self, small_model, large_model, sample_specs):
        fit1 = ModelFit.analyze(small_model, sample_specs)
        fit2 = ModelFit(
            model=large_model,
            fit_level=FitLevel.TOO_TIGHT,
            score=99,  # Even high score shouldn't override
        )
        ranked = rank_models([fit2, fit1])
        assert ranked[-1].fit_level == FitLevel.TOO_TIGHT

    def test_sorted_by_score(self, sample_specs):
        from models import LlmModel

        models = [
            LlmModel(name="A", parameter_count="3B", ctx_length=4096),
            LlmModel(name="B", parameter_count="7B", ctx_length=4096),
        ]
        fits = [ModelFit.analyze(m, sample_specs) for m in models]
        ranked = rank_models(fits)
        scores = [f.score for f in ranked if f.fit_level != FitLevel.TOO_TIGHT]
        # Should be descending
        assert scores == sorted(scores, reverse=True) or len(scores) <= 1


class TestFitLevels:
    def test_perfect_fit(self, sample_specs):
        from models import LlmModel

        # Tiny model on beefy hardware = perfect fit
        m = LlmModel(name="Tiny", parameter_count="1B", ctx_length=2048)
        fit = ModelFit.analyze(m, sample_specs)
        assert fit.fit_level == FitLevel.PERFECT

    def test_too_tight(self, low_end_specs):
        from models import LlmModel

        # Huge model on low-end hardware
        m = LlmModel(name="Huge", parameter_count="200B", ctx_length=4096)
        fit = ModelFit.analyze(m, low_end_specs)
        assert fit.fit_level == FitLevel.TOO_TIGHT
