"""Resource planning — estimate hardware requirements for running specific models."""

import logging
from dataclasses import dataclass, field
from enum import Enum

from hw import SystemSpecs, effective_bandwidth_gbps, enabled_vram_gb
from models import QUANT_BPP, GGUF_QUANT_HIERARCHY, KvQuant, LlmModel

logger = logging.getLogger(__name__)


class PlanRunPath(str, Enum):
    GPU = "Full GPU"
    CPU_OFFLOAD = "CPU Offload"
    CPU_ONLY = "CPU Only"


@dataclass
class HardwareEstimate:
    """Minimum or recommended hardware for a given run path."""

    vram_gb: float | None = None
    ram_gb: float = 0.0
    cpu_cores: int = 4


@dataclass
class PathEstimate:
    """Estimate for a single execution path."""

    path: PlanRunPath
    feasible: bool = False
    minimum: HardwareEstimate | None = None
    recommended: HardwareEstimate | None = None
    estimated_tps: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class PlanRequest:
    """Input parameters for resource planning."""

    context_window: int = 4096
    quantization: str | None = None
    target_tps: float | None = None
    kv_quant: KvQuant | None = None


def plan_model(
    model: LlmModel,
    request: PlanRequest,
    specs: SystemSpecs | None = None,
) -> list[PathEstimate]:
    """Estimate hardware requirements across execution paths."""
    quant = request.quantization or model.quantization
    ctx = request.context_window
    bpp = QUANT_BPP.get(quant, 0.5)
    weight_gb = model.params_b() * bpp
    kv_gb = model._kv_cache_gb(ctx, request.kv_quant or KvQuant.FP16)
    overhead = weight_gb * 0.10
    total_mem = weight_gb + kv_gb + overhead

    results = []

    # --- Full GPU path ---
    gpu_est = PathEstimate(path=PlanRunPath.GPU)
    gpu_est.minimum = HardwareEstimate(
        vram_gb=round(total_mem, 1),
        ram_gb=round(total_mem * 0.5, 1),  # Some system RAM still needed
        cpu_cores=4,
    )
    gpu_est.recommended = HardwareEstimate(
        vram_gb=round(total_mem * 1.3, 1),  # 30% headroom
        ram_gb=round(total_mem * 0.5, 1),
        cpu_cores=8,
    )
    effective_vram = enabled_vram_gb(specs) if specs and specs.gpus else (specs.total_gpu_vram_gb if specs else 0.0)
    effective_bw = effective_bandwidth_gbps(specs) if specs else 0.0
    if specs and specs.has_gpu and effective_vram >= total_mem:
        gpu_est.feasible = True
        if effective_bw > 0:
            gpu_est.estimated_tps = round(effective_bw / weight_gb, 1)
    elif not specs:
        gpu_est.feasible = True  # Unknown — assume possible
        gpu_est.estimated_tps = 0.0
    gpu_est.notes.append(f"Requires {total_mem:.1f} GB VRAM ({quant})")
    results.append(gpu_est)

    # --- CPU Offload path ---
    offload_est = PathEstimate(path=PlanRunPath.CPU_OFFLOAD)
    offload_vram = round(weight_gb * 0.5, 1)  # Keep ~50% weights in VRAM
    offload_ram = round(total_mem - offload_vram + 4, 1)  # Rest in RAM + OS overhead
    offload_est.minimum = HardwareEstimate(
        vram_gb=round(weight_gb * 0.3, 1),
        ram_gb=round(total_mem + 2, 1),
        cpu_cores=4,
    )
    offload_est.recommended = HardwareEstimate(
        vram_gb=offload_vram,
        ram_gb=offload_ram,
        cpu_cores=8,
    )
    if specs:
        combined = (effective_vram if specs.has_gpu else 0) + specs.total_ram_gb
        offload_est.feasible = combined >= total_mem
        if effective_bw > 0:
            offload_est.estimated_tps = round(effective_bw / weight_gb * 0.35, 1)
    else:
        offload_est.feasible = True
    offload_est.notes.append("Split between GPU VRAM and system RAM")
    results.append(offload_est)

    # --- CPU Only path ---
    cpu_est = PathEstimate(path=PlanRunPath.CPU_ONLY)
    cpu_est.minimum = HardwareEstimate(
        vram_gb=None,
        ram_gb=round(total_mem + 4, 1),  # OS + other processes
        cpu_cores=4,
    )
    cpu_est.recommended = HardwareEstimate(
        vram_gb=None,
        ram_gb=round(total_mem * 1.5 + 4, 1),
        cpu_cores=max(8, model.params_b() // 5),
    )
    if specs:
        cpu_est.feasible = specs.total_ram_gb >= total_mem
    else:
        cpu_est.feasible = True
    cpu_est.notes.append(f"Requires {total_mem + 4:.1f} GB system RAM minimum")
    cpu_est.notes.append("Significantly slower than GPU inference")

    # Rough CPU TPS estimate
    params = model.params_b()
    if params <= 7:
        cpu_est.estimated_tps = 8.0
    elif params <= 13:
        cpu_est.estimated_tps = 4.0
    elif params <= 34:
        cpu_est.estimated_tps = 2.0
    else:
        cpu_est.estimated_tps = 0.5

    results.append(cpu_est)

    # --- Find cheaper quant alternatives if nothing fits ---
    if specs and not any(r.feasible for r in results):
        for alt_q in GGUF_QUANT_HIERARCHY:
            alt_mem = model.estimate_memory_gb(alt_q, ctx)
            if alt_mem <= specs.total_ram_gb:
                for r in results:
                    r.notes.append(
                        f"Consider {alt_q} quantization ({alt_mem:.1f} GB) to fit"
                    )
                break

    return results
