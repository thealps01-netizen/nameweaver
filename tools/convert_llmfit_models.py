"""Convert llmfit's hf_models.json to Nameweaver's models.json format."""

import json
import re
import sys
from pathlib import Path

# Use case mapping from llmfit's free-text to our enum
USE_CASE_MAP = {
    "general": "general",
    "coding": "coding",
    "code": "coding",
    "reasoning": "reasoning",
    "chat": "chat",
    "multimodal": "multimodal",
    "vision": "multimodal",
    "embedding": "embedding",
    "embeddings": "embedding",
}


def infer_use_case(raw: str, name: str, caps: list) -> str:
    """Map llmfit's free-text use_case to our enum values."""
    raw_lower = raw.lower()
    name_lower = name.lower()

    # Check direct mapping
    for key, val in USE_CASE_MAP.items():
        if key in raw_lower:
            return val

    # Infer from capabilities
    if "vision" in caps:
        return "multimodal"

    # Infer from name
    if any(k in name_lower for k in ("code", "coder", "starcoder", "codellama")):
        return "coding"
    if any(k in name_lower for k in ("-vl", "vision", "llava", "pixtral")):
        return "multimodal"
    if any(k in name_lower for k in ("-r1", "reasoning", "qwq", "thinking")):
        return "reasoning"
    if any(k in name_lower for k in ("embed", "bge", "-e5-")):
        return "embedding"
    if any(k in name_lower for k in ("instruct", "chat", "assistant")):
        return "chat"

    return "general"


def map_capabilities(caps: list) -> list:
    """Normalize capability names."""
    result = []
    for c in caps:
        c_lower = c.lower().replace(" ", "_")
        if c_lower in ("vision",):
            result.append("vision")
        elif c_lower in ("tool_use", "tooluse"):
            result.append("tool_use")
        else:
            result.append(c_lower)
    return result


def extract_param_count(raw: str, params_raw: int | None) -> str:
    """Convert parameter count to human-readable format."""
    if raw and raw not in ("unknown", ""):
        return raw

    if params_raw and params_raw > 0:
        b = params_raw / 1e9
        if b >= 1:
            return f"{b:.1f}B"
        else:
            m = params_raw / 1e6
            return f"{m:.0f}M"

    return ""


def convert_model(entry: dict) -> dict | None:
    """Convert a single llmfit model entry to Nameweaver format."""
    name = entry.get("name", "")
    if not name:
        return None

    # Skip test/tiny models with very small param counts
    params_raw = entry.get("parameters_raw", 0) or 0
    if params_raw > 0 and params_raw < 50_000_000:  # < 50M params
        # Keep embeddings which can be small
        use_case = entry.get("use_case", "")
        if "embed" not in use_case.lower() and "embed" not in name.lower():
            return None

    # Skip test/internal models
    name_lower = name.lower()
    if any(skip in name_lower for skip in (
        "tiny-random", "peft-internal", "test-", "dummy", "debug",
    )):
        return None

    caps = map_capabilities(entry.get("capabilities", []))
    use_case = infer_use_case(entry.get("use_case", ""), name, caps)

    param_str = extract_param_count(
        entry.get("parameter_count", ""),
        params_raw,
    )

    # Extract provider from name (org/model format)
    provider = entry.get("provider", "")
    if not provider and "/" in name:
        provider = name.split("/")[0]

    # Short name (remove org prefix for display)
    display_name = name.split("/")[-1] if "/" in name else name

    return {
        "name": display_name,
        "provider": provider,
        "parameter_count": param_str,
        "ram_gb": round(entry.get("min_ram_gb", 0) or 0, 1),
        "vram_gb": round(entry.get("min_vram_gb", 0) or 0, 1),
        "format": entry.get("format", "gguf"),
        "quantization": entry.get("quantization", "Q4_K_M"),
        "n_layers": 0,  # Not in llmfit's JSON, will be fetched via HF API
        "attention_heads": 0,
        "hidden_dim": 0,
        "vocab_size": 0,
        "ctx_length": entry.get("context_length", 4096) or 4096,
        "use_case": use_case,
        "capabilities": caps,
        "expert_count": entry.get("num_experts", 0) or 0,
        "active_experts": entry.get("active_experts", 0) or 0,
        "license": "",  # Not in llmfit's JSON
        "release_date": entry.get("release_date", "") or "",
    }


def main():
    src = Path(__file__).parent / "llmfit_raw_models.json"
    dst = Path(__file__).parent.parent / "data" / "models.json"

    if not src.exists():
        print(f"Source not found: {src}")
        sys.exit(1)

    with open(src, encoding="utf-8") as f:
        raw = json.load(f)

    print(f"Input: {len(raw)} models from llmfit")

    converted = []
    skipped = 0
    for entry in raw:
        result = convert_model(entry)
        if result:
            converted.append(result)
        else:
            skipped += 1

    # Deduplicate by name
    seen = set()
    deduped = []
    for m in converted:
        key = m["name"].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(m)

    # Sort by provider, then name
    deduped.sort(key=lambda m: (m["provider"].lower(), m["name"].lower()))

    with open(dst, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)

    print(f"Output: {len(deduped)} models (skipped {skipped} test/tiny models)")
    print(f"Written to: {dst}")

    # Stats
    use_cases = {}
    for m in deduped:
        uc = m["use_case"]
        use_cases[uc] = use_cases.get(uc, 0) + 1
    print(f"\nUse case distribution: {json.dumps(use_cases, indent=2)}")

    providers = set(m["provider"] for m in deduped)
    print(f"Unique providers: {len(providers)}")

    moe = [m for m in deduped if m["expert_count"] > 0]
    print(f"MoE models: {len(moe)}")

    vision = [m for m in deduped if "vision" in m["capabilities"]]
    print(f"Vision models: {len(vision)}")


if __name__ == "__main__":
    main()
