"""3-dimension scoring engine — quality, speed, fit.

Ports the core algorithm from llmfit's fit.rs to Python.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from hw import GpuBackend, SystemSpecs, effective_bandwidth_gbps, enabled_vram_gb
from models import (
    QUANT_BPP,
    QUANT_QUALITY_MULT,
    QUANT_SPEED_MULT,
    GGUF_QUANT_HIERARCHY,
    LlmModel,
    UseCase,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FitLevel(str, Enum):
    PERFECT = "Perfect"
    GOOD = "Good"
    MARGINAL = "Marginal"
    TOO_TIGHT = "Too Tight"

    @property
    def rank(self) -> int:
        return {
            FitLevel.PERFECT: 0,
            FitLevel.GOOD: 1,
            FitLevel.MARGINAL: 2,
            FitLevel.TOO_TIGHT: 3,
        }[self]

    @property
    def short_hint(self) -> str:
        """One-line descriptor with the utilization threshold."""
        return {
            FitLevel.PERFECT:   "plenty of headroom (≤60%)",
            FitLevel.GOOD:      "comfortable, small headroom (60–80%)",
            FitLevel.MARGINAL:  "barely fits (80–95%)",
            FitLevel.TOO_TIGHT: "doesn't fit in memory (>95%)",
        }[self]


class RunMode(str, Enum):
    GPU = "GPU"
    MOE_OFFLOAD = "MoE Offload"
    CPU_OFFLOAD = "CPU Offload"
    CPU_ONLY = "CPU Only"
    # Reserved: currently not assigned by _determine_run_mode. Tensor-parallel
    # runners (vLLM, TGI) are referenced in the multi-GPU layer-split warning
    # (_maybe_warn_layer_split) but not distinguished here because Nameweaver's
    # scoring doesn't know which runner the user will invoke. Kept as an enum
    # value so downstream UI (color map, filter combo) can stay stable.
    TENSOR_PARALLEL = "Tensor Parallel"


class SortColumn(str, Enum):
    SCORE = "score"
    TPS = "tps"
    PARAMS = "params"
    MEM_PCT = "mem_pct"
    CTX = "ctx"
    RELEASE_DATE = "release_date"
    USE_CASE = "use_case"
    PROVIDER = "provider"


# ---------------------------------------------------------------------------
# Score components
# ---------------------------------------------------------------------------


@dataclass
class ScoreComponents:
    quality: float = 0.0
    speed: float = 0.0
    fit: float = 0.0


@dataclass
class ModelFit:
    """Result of analyzing a model's fit against system hardware."""

    model: LlmModel
    fit_level: FitLevel = FitLevel.TOO_TIGHT
    run_mode: RunMode = RunMode.CPU_ONLY
    memory_required_gb: float = 0.0
    memory_available_gb: float = 0.0
    utilization_pct: float = 0.0
    score: float = 0.0
    score_components: ScoreComponents = field(default_factory=ScoreComponents)
    estimated_tps: float = 0.0
    best_quant: str = ""
    notes: list[str] = field(default_factory=list)
    installed: bool = False

    @classmethod
    def analyze(
        cls,
        model: LlmModel,
        specs: SystemSpecs,
        context_limit: int | None = None,
        preference: float = 0.5,
    ) -> "ModelFit":
        """Analyze how well a model fits the given hardware.

        ``preference`` biases the composite score toward quality (1.0) or
        speed (0.0); 0.5 uses the use-case defaults unchanged.
        """
        result = cls(model=model)

        ctx = context_limit or model.ctx_length

        # Determine available memory and run mode
        _determine_run_mode(result, model, specs, ctx)

        # Find best quantization for the budget
        _select_best_quant(result, model, specs)

        # Calculate memory requirements with selected quant
        result.memory_required_gb = model.estimate_memory_gb(result.best_quant, ctx)

        # Determine fit level
        _classify_fit_level(result)

        # Estimate tokens per second
        result.estimated_tps = _estimate_tps(model, result.best_quant, specs, result.run_mode)

        # Calculate score components
        result.score_components = _compute_scores(model, result, specs, ctx)

        # Weighted composite score
        result.score = _weighted_score(result.score_components, model.get_use_case(), preference)

        return result


# ---------------------------------------------------------------------------
# Run mode determination
# ---------------------------------------------------------------------------


# OS + other processes typically consume ~15-25% of RAM under load.
# Use 80% as a practical upper bound for model memory.
_RAM_USABLE_FRACTION = 0.80
# CPU offload: weights partially in RAM slow inference drastically.
# Past ~50% RAM-resident, the model is effectively CPU-bound. Use this
# to keep quant picker from selecting huge quants that "fit" but crawl.
_OFFLOAD_RAM_BUDGET_FRACTION = 0.60


def _maybe_warn_layer_split(
    result: ModelFit, model: LlmModel, specs: SystemSpecs, quant: str
) -> None:
    """Emit a note when aggregate VRAM fits but a single layer might not.

    llama.cpp / Ollama / LM Studio split a model **by layer** across GPUs;
    each layer must fit in a single card's VRAM. For most models layers
    are 200-500 MB and this is never a problem, but 200B+ dense models
    with ~1-2 GB layers can fail on 2×8GB cards even when combined VRAM
    is enough. Also, Tensor-Parallel runners (vLLM, TGI) split tensors
    *within* a layer and avoid this constraint — so the warning points
    the user at that option.
    """
    if specs.gpu_count <= 1 or model.n_layers <= 0:
        return
    enabled = [g for g in specs.gpus if g.enabled and g.vram_gb > 0]
    if len(enabled) <= 1:
        return
    bpp = QUANT_BPP.get(quant, 0.5)
    weight_gb = model.params_b() * bpp
    per_layer_gb = weight_gb / model.n_layers
    # Add a small activation budget per layer (~30% of weights)
    per_layer_with_act = per_layer_gb * 1.3
    smallest_gpu_vram = min(g.vram_gb for g in enabled)
    if per_layer_with_act > smallest_gpu_vram:
        result.notes.append(
            f"⚠ Single layer ≈{per_layer_with_act:.1f} GB exceeds smallest "
            f"enabled GPU ({smallest_gpu_vram:.1f} GB). llama.cpp/Ollama "
            f"may fail; use a tensor-parallel runner (vLLM/TGI) instead."
        )


def _practical_probe_quant(model: LlmModel) -> str:
    """Pick a realistic quant for run_mode decisions.

    ``model.quantization`` is often the repo's default (F16/BF16 for HF
    originals). Using it for the run_mode probe misclassifies models as
    CPU_ONLY even when a Q4 quant would fit comfortably in VRAM.
    """
    fmt = model.format.lower()
    if fmt == "mlx":
        return "mlx-4bit"
    if fmt == "awq":
        return "AWQ-4bit"
    if fmt == "gptq":
        return "GPTQ-4bit"
    return "Q4_K_M"  # GGUF default — widely produced, balanced quality/size


def _determine_run_mode(
    result: ModelFit, model: LlmModel, specs: SystemSpecs, ctx: int | None = None
) -> None:
    """Determine the best execution mode based on available hardware.

    Apple Silicon / unified memory systems get a dedicated dispatch path
    because their VRAM is carved from the same RAM pool — adding VRAM +
    RAM for an "offload" mode would double-count the same physical bytes.
    """
    # Use enabled GPUs only — the user may have disabled iGPUs or spare cards
    effective_vram = enabled_vram_gb(specs) if specs.gpus else specs.total_gpu_vram_gb

    # --- Apple Silicon / unified memory: single shared pool ---
    if specs.unified_memory:
        # effective_vram on Apple is already ~75% of total RAM (see
        # hw.py::_detect_apple_silicon). Don't add total_ram_gb again.
        if not specs.has_gpu or effective_vram <= 0:
            result.run_mode = RunMode.CPU_ONLY
            result.memory_available_gb = round(specs.total_ram_gb * _RAM_USABLE_FRACTION, 1)
            return
        result.run_mode = RunMode.GPU
        result.memory_available_gb = effective_vram
        return

    # --- Discrete GPU / CPU-only dispatch ---
    if not specs.has_gpu or effective_vram <= 0:
        result.run_mode = RunMode.CPU_ONLY
        result.memory_available_gb = round(specs.total_ram_gb * _RAM_USABLE_FRACTION, 1)
        return

    # Probe with a practical quant rather than the repo's default (F16/BF16
    # would wrongly push Q4-friendly models into CPU_ONLY).
    probe_quant = _practical_probe_quant(model)
    min_mem = model.estimate_memory_gb(probe_quant, ctx)

    # Full GPU fit?
    if min_mem <= effective_vram:
        result.run_mode = RunMode.GPU
        result.memory_available_gb = effective_vram
        _maybe_warn_layer_split(result, model, specs, probe_quant)
        return

    # MoE offload: active experts in VRAM, rest in RAM
    if model.is_moe():
        active_params = model.active_params_b()
        active_mem = active_params * QUANT_BPP.get(probe_quant, 0.5)
        if active_mem <= effective_vram:
            result.run_mode = RunMode.MOE_OFFLOAD
            # Available = VRAM for active experts + usable RAM for the rest
            result.memory_available_gb = round(
                effective_vram + specs.total_ram_gb * _RAM_USABLE_FRACTION, 1
            )
            result.notes.append(
                f"Active experts ({active_params:.1f}B params) fit in VRAM, "
                f"rest offloaded to RAM"
            )
            return

    # CPU offload: partial GPU + RAM, but realistic budget (too much
    # RAM-resident weight = unusably slow).
    offload_ram_budget = specs.total_ram_gb * _OFFLOAD_RAM_BUDGET_FRACTION
    total_mem = effective_vram + offload_ram_budget
    if min_mem <= total_mem:
        result.run_mode = RunMode.CPU_OFFLOAD
        result.memory_available_gb = round(total_mem, 1)
        gpu_pct = effective_vram / total_mem * 100 if total_mem > 0 else 0.0
        result.notes.append(
            f"~{gpu_pct:.0f}% GPU, rest CPU offloaded (quality/speed trade-off)"
        )
        return

    # CPU only — use full usable RAM as budget
    result.run_mode = RunMode.CPU_ONLY
    result.memory_available_gb = round(specs.total_ram_gb * _RAM_USABLE_FRACTION, 1)


def _select_best_quant(result: ModelFit, model: LlmModel, specs: SystemSpecs) -> None:
    """Select the best quantization that fits the budget, mode-aware.

    Without mode awareness, a CPU_OFFLOAD result.memory_available_gb of
    "VRAM + RAM" encourages picking F16 that technically fits but makes
    inference unusably slow. We cap the quant-selection budget to what
    each mode realistically supports with acceptable throughput.
    """
    if result.run_mode == RunMode.GPU:
        # All weights in VRAM — no penalty
        budget = result.memory_available_gb
    elif result.run_mode == RunMode.MOE_OFFLOAD:
        # Use the conservative budget (active in VRAM + usable RAM for
        # inactive experts). Quant picker can be a bit generous here since
        # inactive experts don't affect token-latency as badly.
        budget = result.memory_available_gb
    elif result.run_mode == RunMode.CPU_OFFLOAD:
        # Cap at VRAM + 30% RAM — past that, every RAM-resident byte
        # costs several ms/token. Prefer smaller quants here.
        effective_vram = (
            enabled_vram_gb(specs) if specs.gpus else specs.total_gpu_vram_gb
        )
        budget = effective_vram + specs.total_ram_gb * 0.30
    elif result.run_mode == RunMode.CPU_ONLY:
        # Already the usable-RAM-fraction; don't inflate further.
        budget = result.memory_available_gb
    else:
        budget = result.memory_available_gb

    best = model.best_quant_for_budget(max(budget, 0.0))
    if best:
        result.best_quant = best[0]
    else:
        # Nothing fits well — use the smallest available quant
        result.best_quant = GGUF_QUANT_HIERARCHY[-1] if model.format == "gguf" else "Q4_K_M"


def _classify_fit_level(result: ModelFit) -> None:
    """Classify how well the model fits based on memory utilization."""
    if result.memory_available_gb <= 0:
        result.fit_level = FitLevel.TOO_TIGHT
        result.utilization_pct = 100.0
        return

    util = (result.memory_required_gb / result.memory_available_gb) * 100
    result.utilization_pct = min(util, 100.0)

    if util <= 60:
        result.fit_level = FitLevel.PERFECT
    elif util <= 80:
        result.fit_level = FitLevel.GOOD
    elif util <= 95:
        result.fit_level = FitLevel.MARGINAL
    else:
        result.fit_level = FitLevel.TOO_TIGHT


# ---------------------------------------------------------------------------
# TPS estimation
# ---------------------------------------------------------------------------


def _estimate_tps(
    model: LlmModel,
    quant: str,
    specs: SystemSpecs,
    run_mode: RunMode,
) -> float:
    """Estimate tokens per second using bandwidth-based model."""
    params = model.params_b()
    if params <= 0:
        return 0.0

    bpp = QUANT_BPP.get(quant, 0.5)
    speed_mult = QUANT_SPEED_MULT.get(quant, 1.0)

    # Model weight size in GB
    weight_gb = params * bpp

    # Use enabled GPUs' dominant bandwidth (supersedes legacy primary-only field)
    bw = effective_bandwidth_gbps(specs)

    # params > 0 (checked above) and bpp > 0 → weight_gb > 0 is guaranteed.
    if run_mode == RunMode.GPU and bw > 0:
        # Bandwidth-bound: each token reads full model weights once
        tps = (bw / weight_gb) * speed_mult
    elif run_mode == RunMode.MOE_OFFLOAD and bw > 0:
        # Only active experts read from VRAM
        active_weight = model.active_params_b() * bpp
        if active_weight <= 0:
            return 0.0
        tps = (bw / active_weight) * speed_mult * 0.7  # Overhead for offload coordination
    elif run_mode == RunMode.CPU_OFFLOAD:
        # Mixed: slower due to PCIe bottleneck
        # Estimate ~30-50% of pure GPU speed
        if bw > 0:
            tps = (bw / weight_gb) * 0.35
        else:
            tps = _cpu_tps_estimate(params, speed_mult, specs)
    else:
        # CPU only
        tps = _cpu_tps_estimate(params, speed_mult, specs)

    return round(max(tps, 0.1), 1)


def _cpu_tps_estimate(params: float, speed_mult: float, specs: SystemSpecs) -> float:
    """Rough CPU-only TPS estimate based on model size and core count."""
    # Smaller models are faster
    if params <= 1:
        base = 30.0
    elif params <= 3:
        base = 15.0
    elif params <= 7:
        base = 8.0
    elif params <= 13:
        base = 4.0
    elif params <= 34:
        base = 2.0
    elif params <= 70:
        base = 1.0
    else:
        base = 0.3

    # Core count bonus (diminishing returns)
    core_mult = min(specs.total_cpu_cores / 8.0, 2.0)
    return base * speed_mult * core_mult


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------


def _compute_scores(
    model: LlmModel, result: ModelFit, specs: SystemSpecs, ctx: int
) -> ScoreComponents:
    return ScoreComponents(
        quality=_quality_score(model, result.best_quant),
        speed=_speed_score(result.estimated_tps),
        fit=_fit_score(result.utilization_pct, result.fit_level),
    )


def _quality_score(model: LlmModel, quant: str) -> float:
    """Score 0-100 based on model size and quantization quality retention."""
    params = model.params_b()

    # Base quality from parameter count (diminishing returns)
    if params <= 0:
        base = 10.0
    elif params <= 1:
        base = 25.0
    elif params <= 3:
        base = 40.0
    elif params <= 7:
        base = 55.0
    elif params <= 13:
        base = 65.0
    elif params <= 34:
        base = 75.0
    elif params <= 70:
        base = 85.0
    elif params <= 200:
        base = 92.0
    else:
        base = 95.0

    # Model family reputation bonus
    name_lower = model.name.lower()
    provider_lower = model.provider.lower()

    family_bonus = 0.0
    if "llama-3" in name_lower or "llama-3" in provider_lower:
        family_bonus = 5.0
    elif "qwen2.5" in name_lower or "qwen3" in name_lower:
        family_bonus = 5.0
    elif "deepseek-r1" in name_lower:
        family_bonus = 7.0
    elif "gemma-3" in name_lower:
        family_bonus = 4.0
    elif "phi-4" in name_lower:
        family_bonus = 5.0
    elif "command-r" in name_lower:
        family_bonus = 3.0

    # Quantization penalty
    quant_mult = QUANT_QUALITY_MULT.get(quant, 0.90)

    return min((base + family_bonus) * quant_mult, 100.0)


def _speed_score(tps: float) -> float:
    """Score 0-100 based on estimated tokens per second."""
    if tps <= 0:
        return 0.0
    elif tps >= 100:
        return 100.0
    elif tps >= 60:
        return 90.0 + (tps - 60) / 40 * 10
    elif tps >= 30:
        return 70.0 + (tps - 30) / 30 * 20
    elif tps >= 15:
        return 50.0 + (tps - 15) / 15 * 20
    elif tps >= 5:
        return 25.0 + (tps - 5) / 10 * 25
    else:
        return tps / 5 * 25


def _fit_score(utilization_pct: float, fit_level: FitLevel) -> float:
    """Score 0-100 based on memory utilization. Optimal is 50-80%."""
    if fit_level == FitLevel.TOO_TIGHT:
        return max(10.0, 30.0 - (utilization_pct - 95) * 2)

    if utilization_pct <= 30:
        # Under-utilized — wasted capacity
        return 60.0 + utilization_pct
    elif utilization_pct <= 50:
        return 85.0 + (utilization_pct - 30) * 0.5
    elif utilization_pct <= 80:
        # Sweet spot
        return 95.0 + (utilization_pct - 50) * (5.0 / 30.0)
    elif utilization_pct <= 95:
        # Getting tight but still OK
        return 100.0 - (utilization_pct - 80) * 2
    else:
        return max(10.0, 70.0 - (utilization_pct - 95) * 6)


# ---------------------------------------------------------------------------
# Weighted composite score per use case
# ---------------------------------------------------------------------------

USE_CASE_WEIGHTS: dict[UseCase, tuple[float, float, float]] = {
    #                      quality  speed  fit
    UseCase.GENERAL:      (0.40,   0.30,  0.30),
    UseCase.CODING:       (0.60,   0.20,  0.20),
    UseCase.REASONING:    (0.55,   0.15,  0.30),
    UseCase.CHAT:         (0.35,   0.40,  0.25),
    UseCase.MULTIMODAL:   (0.45,   0.25,  0.30),
    UseCase.EMBEDDING:    (0.25,   0.45,  0.30),
}


def _weighted_score(
    components: ScoreComponents,
    use_case: UseCase,
    preference: float = 0.5,
) -> float:
    """Compute weighted composite score.

    ``preference`` ∈ [0.0, 1.0] biases the score toward quality (1.0) or
    speed (0.0). At 0.5 the use-case defaults are used untouched. The bias
    is a multiplicative warp on quality/speed weights that is renormalized
    so the total still sums to 1.0 — the fit weight stays intact.
    """
    w = USE_CASE_WEIGHTS.get(use_case, USE_CASE_WEIGHTS[UseCase.GENERAL])
    q_w, s_w, f_w = w

    # Bias: preference=0 → speed ×1.5, quality ×0.5; preference=1 → reverse.
    # Range for each multiplier: 0.5 .. 1.5, centered at 1.0 when preference=0.5.
    p = max(0.0, min(1.0, preference))
    q_mult = 0.5 + p
    s_mult = 1.5 - p
    q_w *= q_mult
    s_w *= s_mult

    # Renormalize so quality+speed+fit sum back to 1.0
    total = q_w + s_w + f_w
    if total > 0:
        scale = 1.0 / total
        q_w *= scale
        s_w *= scale
        f_w *= scale

    score = (
        components.quality * q_w
        + components.speed * s_w
        + components.fit * f_w
    )
    return round(min(score, 100.0), 1)


def apply_preference(fits: list[ModelFit], preference: float) -> None:
    """Recompute ``fit.score`` in-place using stored components + new preference.

    Avoids re-running ``ModelFit.analyze`` (expensive) when only the
    quality/speed bias changes. After this, call ``rank_models`` to re-sort.
    """
    for fit in fits:
        fit.score = _weighted_score(
            fit.score_components, fit.model.get_use_case(), preference
        )


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def rank_models(
    fits: list[ModelFit],
    sort_by: SortColumn = SortColumn.SCORE,
    installed_first: bool = True,
) -> list[ModelFit]:
    """Sort model fits with TOO_TIGHT always last."""

    def sort_key(mf: ModelFit) -> tuple:
        # Primary: installed models first (if enabled)
        installed = 0 if (installed_first and mf.installed) else 1
        # Secondary: TOO_TIGHT always last
        tight = 1 if mf.fit_level == FitLevel.TOO_TIGHT else 0

        # Tertiary: sort column (descending = negate)
        if sort_by == SortColumn.SCORE:
            val = -mf.score
        elif sort_by == SortColumn.TPS:
            val = -mf.estimated_tps
        elif sort_by == SortColumn.PARAMS:
            val = -mf.model.params_b()
        elif sort_by == SortColumn.MEM_PCT:
            val = -mf.utilization_pct
        elif sort_by == SortColumn.CTX:
            val = -mf.model.ctx_length
        elif sort_by == SortColumn.RELEASE_DATE:
            val = mf.model.release_date  # Lexicographic, newer first needs reverse
        elif sort_by == SortColumn.USE_CASE:
            val = mf.model.use_case
        elif sort_by == SortColumn.PROVIDER:
            val = mf.model.provider
        else:
            val = -mf.score

        return (installed, tight, val)

    return sorted(fits, key=sort_key)


def analyze_all(
    models: list[LlmModel],
    specs: SystemSpecs,
    context_limit: int | None = None,
    preference: float = 0.5,
) -> list[ModelFit]:
    """Analyze all models against the given hardware and return ranked results."""
    fits = []
    for model in models:
        try:
            fit = ModelFit.analyze(model, specs, context_limit, preference=preference)
            fits.append(fit)
        except Exception as exc:
            logger.debug("Failed to analyze %s: %s", model.name, exc)
    return rank_models(fits)
