"""LLM model definitions, quantization tables, and model database loading."""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class UseCase(str, Enum):
    GENERAL = "general"
    CODING = "coding"
    REASONING = "reasoning"
    CHAT = "chat"
    MULTIMODAL = "multimodal"
    EMBEDDING = "embedding"


class ModelFormat(str, Enum):
    GGUF = "gguf"
    AWQ = "awq"
    GPTQ = "gptq"
    MLX = "mlx"
    SAFETENSORS = "safetensors"


class Capability(str, Enum):
    VISION = "vision"
    TOOL_USE = "tool_use"


class KvQuant(str, Enum):
    FP16 = "fp16"
    FP8 = "fp8"
    Q8_0 = "q8_0"
    Q4_0 = "q4_0"


# ---------------------------------------------------------------------------
# Quantization lookup tables
# ---------------------------------------------------------------------------

# Bytes per parameter for each quantization level
QUANT_BPP: dict[str, float] = {
    "F32": 4.0,
    "F16": 2.0,
    "BF16": 2.0,
    "Q8_0": 1.0,
    "Q6_K": 0.75,
    "Q5_K_M": 0.625,
    "Q5_K_S": 0.625,
    "Q4_K_M": 0.5,
    "Q4_K_S": 0.5,
    "Q4_0": 0.5,
    "Q3_K_M": 0.4375,
    "Q3_K_S": 0.4375,
    "Q2_K": 0.3125,
    "IQ4_XS": 0.5,
    "IQ3_XXS": 0.375,
    "IQ2_XXS": 0.25,
    # AWQ / GPTQ
    "AWQ-4bit": 0.5,
    "GPTQ-4bit": 0.5,
    "GPTQ-8bit": 1.0,
    # MLX
    "mlx-4bit": 0.5,
    "mlx-8bit": 1.0,
}

# Quality multiplier — how much quality degrades at each quant level
QUANT_QUALITY_MULT: dict[str, float] = {
    "F32": 1.0,
    "F16": 1.0,
    "BF16": 1.0,
    "Q8_0": 0.98,
    "Q6_K": 0.96,
    "Q5_K_M": 0.94,
    "Q5_K_S": 0.93,
    "Q4_K_M": 0.90,
    "Q4_K_S": 0.89,
    "Q4_0": 0.88,
    "Q3_K_M": 0.85,
    "Q3_K_S": 0.83,
    "Q2_K": 0.75,
    "IQ4_XS": 0.90,
    "IQ3_XXS": 0.82,
    "IQ2_XXS": 0.70,
    "AWQ-4bit": 0.91,
    "GPTQ-4bit": 0.90,
    "GPTQ-8bit": 0.98,
    "mlx-4bit": 0.90,
    "mlx-8bit": 0.98,
}

# Speed multiplier — relative decode speed at each quant level
QUANT_SPEED_MULT: dict[str, float] = {
    "F32": 0.5,
    "F16": 1.0,
    "BF16": 1.0,
    "Q8_0": 1.3,
    "Q6_K": 1.5,
    "Q5_K_M": 1.7,
    "Q5_K_S": 1.7,
    "Q4_K_M": 2.0,
    "Q4_K_S": 2.0,
    "Q4_0": 2.0,
    "Q3_K_M": 2.2,
    "Q3_K_S": 2.2,
    "Q2_K": 2.5,
    "IQ4_XS": 2.0,
    "IQ3_XXS": 2.2,
    "IQ2_XXS": 2.5,
    "AWQ-4bit": 2.0,
    "GPTQ-4bit": 2.0,
    "GPTQ-8bit": 1.3,
    "mlx-4bit": 2.0,
    "mlx-8bit": 1.3,
}

GGUF_QUANT_HIERARCHY = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "Q3_K_M", "Q2_K"]
MLX_QUANT_HIERARCHY = ["mlx-8bit", "mlx-4bit"]
AWQ_QUANT_HIERARCHY = ["AWQ-4bit"]
GPTQ_QUANT_HIERARCHY = ["GPTQ-8bit", "GPTQ-4bit"]

# KV cache bytes per token per layer
KV_CACHE_BYTES: dict[KvQuant, float] = {
    KvQuant.FP16: 4.0,
    KvQuant.FP8: 2.0,
    KvQuant.Q8_0: 2.0,
    KvQuant.Q4_0: 1.0,
}


# ---------------------------------------------------------------------------
# LlmModel dataclass
# ---------------------------------------------------------------------------


@dataclass
class LlmModel:
    """Represents a single LLM model with its specifications."""

    name: str
    provider: str = ""
    parameter_count: str = ""  # e.g. "7B", "70B", "8x7B"
    ram_gb: float = 0.0
    vram_gb: float = 0.0
    format: str = "gguf"
    quantization: str = "Q4_K_M"
    n_layers: int = 0
    attention_heads: int = 0
    hidden_dim: int = 0
    vocab_size: int = 0
    ctx_length: int = 4096
    use_case: str = "general"
    capabilities: list[str] = field(default_factory=list)
    expert_count: int = 0
    active_experts: int = 0
    license: str = ""
    release_date: str = ""

    def params_b(self) -> float:
        """Parse parameter count string to billions. E.g. '7B' -> 7.0, '8x7B' -> 56.0"""
        s = self.parameter_count.upper().strip()
        if not s:
            return 0.0

        # MoE pattern: "8x7B"
        moe = re.match(r"(\d+)[xX](\d+\.?\d*)[bB]?", s)
        if moe:
            return float(moe.group(1)) * float(moe.group(2))

        # Standard: "7B", "1.5B", "70B"
        m = re.match(r"(\d+\.?\d*)\s*[bB]?", s)
        if m:
            return float(m.group(1))

        return 0.0

    def is_moe(self) -> bool:
        return self.expert_count > 0 and self.active_experts > 0

    def active_params_b(self) -> float:
        """For MoE models, return active parameter count during inference."""
        if not self.is_moe():
            return self.params_b()
        total = self.params_b()
        if self.expert_count <= 0:
            return total
        # Approximate: shared params + (active/total) * expert params
        # Shared is roughly 30% of total for typical MoE
        shared_ratio = 0.3
        expert_ratio = 1.0 - shared_ratio
        return total * (shared_ratio + expert_ratio * self.active_experts / self.expert_count)

    def estimate_disk_gb(self, quant: str | None = None) -> float:
        """Estimate model weight size on disk in GB."""
        q = quant or self.quantization
        bpp = QUANT_BPP.get(q, 0.5)
        return self.params_b() * bpp

    def estimate_memory_gb(self, quant: str | None = None, ctx: int | None = None) -> float:
        """Estimate total memory needed (weights + KV cache + overhead)."""
        q = quant or self.quantization
        context = ctx or self.ctx_length

        # Model weights
        weights_gb = self.estimate_disk_gb(q)

        # KV cache estimate
        kv_gb = self._kv_cache_gb(context)

        # Overhead (CUDA context, activation memory, etc.) ~10%
        overhead = weights_gb * 0.10

        return weights_gb + kv_gb + overhead

    def _kv_cache_gb(self, ctx: int, kv_quant: KvQuant = KvQuant.FP16) -> float:
        """Estimate KV cache size in GB."""
        if self.n_layers > 0 and self.hidden_dim > 0:
            # Precise calculation using architecture details
            heads = self.attention_heads if self.attention_heads > 0 else 32
            head_dim = self.hidden_dim // heads if heads > 0 else 128
            kv_heads = heads  # Assume GQA ratio 1 if unknown
            bytes_per_token = KV_CACHE_BYTES.get(kv_quant, 4.0)
            # 2 for K and V, per layer
            total_bytes = 2 * self.n_layers * kv_heads * head_dim * ctx * bytes_per_token
            return total_bytes / (1024**3)
        else:
            # Rough approximation based on parameter count
            params = self.params_b()
            if params <= 3:
                return ctx * 0.5 / (1024 * 8)  # ~0.5 bytes per token
            elif params <= 13:
                return ctx * 1.0 / (1024 * 8)
            elif params <= 34:
                return ctx * 2.0 / (1024 * 8)
            else:
                return ctx * 4.0 / (1024 * 8)

    def best_quant_for_budget(
        self, budget_gb: float, ctx: int | None = None
    ) -> tuple[str, float] | None:
        """Find the best quantization level that fits within a memory budget.

        Returns (quant_name, estimated_memory_gb) or None if nothing fits.
        """
        context = ctx or self.ctx_length
        fmt = self.format.lower()

        if fmt == "mlx":
            hierarchy = MLX_QUANT_HIERARCHY
        elif fmt == "awq":
            hierarchy = AWQ_QUANT_HIERARCHY
        elif fmt == "gptq":
            hierarchy = GPTQ_QUANT_HIERARCHY
        else:
            hierarchy = GGUF_QUANT_HIERARCHY

        for q in hierarchy:
            mem = self.estimate_memory_gb(q, context)
            if mem <= budget_gb:
                return (q, mem)

        return None

    def get_use_case(self) -> UseCase:
        try:
            return UseCase(self.use_case.lower())
        except ValueError:
            return UseCase.GENERAL

    def has_capability(self, cap: Capability) -> bool:
        return cap.value in self.capabilities


# ---------------------------------------------------------------------------
# Model database loading
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent / "data"


def load_models(path: Path | None = None) -> list[LlmModel]:
    """Load the model catalog from the embedded JSON file."""
    json_path = path or (_DATA_DIR / "models.json")
    if not json_path.exists():
        logger.warning("Model database not found: %s", json_path)
        return []

    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load model database: %s", exc)
        return []

    if not isinstance(data, list):
        logger.error("Model database must be a JSON array")
        return []

    models = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            model = LlmModel(
                name=entry.get("name", "unknown"),
                provider=entry.get("provider", ""),
                parameter_count=entry.get("parameter_count", ""),
                ram_gb=float(entry.get("ram_gb", 0)),
                vram_gb=float(entry.get("vram_gb", 0)),
                format=entry.get("format", "gguf"),
                quantization=entry.get("quantization", "Q4_K_M"),
                n_layers=int(entry.get("n_layers", 0)),
                attention_heads=int(entry.get("attention_heads", 0)),
                hidden_dim=int(entry.get("hidden_dim", 0)),
                vocab_size=int(entry.get("vocab_size", 0)),
                ctx_length=int(entry.get("ctx_length", 4096)),
                use_case=entry.get("use_case", "general"),
                capabilities=entry.get("capabilities", []),
                expert_count=int(entry.get("expert_count", 0)),
                active_experts=int(entry.get("active_experts", 0)),
                license=entry.get("license", ""),
                release_date=entry.get("release_date", ""),
            )
            models.append(model)
        except (TypeError, ValueError) as exc:
            logger.debug("Skipping malformed model entry: %s", exc)

    logger.info("Loaded %d models from %s", len(models), json_path)
    return models


def merge_models(
    embedded: list[LlmModel],
    cached: list[LlmModel],
) -> list[LlmModel]:
    """Merge embedded catalog with HF-cached models, deduplicating by name.

    Cached models take priority (they may be newer / have richer metadata).
    """
    by_key: dict[str, LlmModel] = {}

    # Embedded first (lower priority)
    for m in embedded:
        by_key[m.name.lower()] = m

    # Cache overwrites
    for m in cached:
        by_key[m.name.lower()] = m

    merged = sorted(by_key.values(), key=lambda m: (m.provider.lower(), m.name.lower()))
    logger.info(
        "Merged catalog: %d embedded + %d cached → %d unique",
        len(embedded),
        len(cached),
        len(merged),
    )
    return merged


def load_cached_models() -> list[LlmModel]:
    """Load models from the HF cache file in the user's config directory."""
    from cfg import config_dir

    cache_path = config_dir() / "hf_cache.json"
    if not cache_path.exists():
        return []

    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load HF cache: %s", exc)
        return []

    if not isinstance(data, dict):
        return []

    models_data = data.get("models", [])
    if not isinstance(models_data, list):
        return []

    models = []
    for entry in models_data:
        if not isinstance(entry, dict):
            continue
        try:
            model = LlmModel(
                name=entry.get("name", "unknown"),
                provider=entry.get("provider", ""),
                parameter_count=entry.get("parameter_count", ""),
                ram_gb=float(entry.get("ram_gb", 0)),
                vram_gb=float(entry.get("vram_gb", 0)),
                format=entry.get("format", "gguf"),
                quantization=entry.get("quantization", "Q4_K_M"),
                n_layers=int(entry.get("n_layers", 0)),
                attention_heads=int(entry.get("attention_heads", 0)),
                hidden_dim=int(entry.get("hidden_dim", 0)),
                vocab_size=int(entry.get("vocab_size", 0)),
                ctx_length=int(entry.get("ctx_length", 4096)),
                use_case=entry.get("use_case", "general"),
                capabilities=entry.get("capabilities", []),
                expert_count=int(entry.get("expert_count", 0)),
                active_experts=int(entry.get("active_experts", 0)),
                license=entry.get("license", ""),
                release_date=entry.get("release_date", ""),
            )
            models.append(model)
        except (TypeError, ValueError) as exc:
            logger.debug("Skipping malformed cached model: %s", exc)

    logger.info("Loaded %d models from HF cache", len(models))
    return models


def load_all_models() -> list[LlmModel]:
    """Load embedded catalog + HF cache and merge them."""
    embedded = load_models()
    cached = load_cached_models()
    if cached:
        return merge_models(embedded, cached)
    return embedded
