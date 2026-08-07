"""HuggingFace Hub API client with caching.

Fetches text-generation / vision-language model metadata from
https://huggingface.co/api and converts entries to Nameweaver's LlmModel.
Results are cached in ``%LOCALAPPDATA%\\Nameweaver\\hf_cache.json``.
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from cfg import config_dir
from models import LlmModel

logger = logging.getLogger(__name__)

HF_API = "https://huggingface.co/api"
HF_MODEL_BASE = "https://huggingface.co"
CACHE_VERSION = 1
USER_AGENT = "Nameweaver/0.2 (+https://github.com/AlexsJones/llmfit)"


# ---------------------------------------------------------------------------
# Parameter / use-case extraction helpers
# ---------------------------------------------------------------------------

_PARAM_B_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[Bb](?![a-zA-Z])")
_PARAM_M_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[Mm](?![a-zA-Z])")
_MOE_RE = re.compile(r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*[Bb]")
_CTX_K_RE = re.compile(r"(\d+)\s*[Kk](?:\s*context|\s*ctx)?")

# Context length inference by family keyword
_CTX_DEFAULTS = {
    "llama-3": 131072,
    "llama3": 131072,
    "qwen2.5": 131072,
    "qwen2": 32768,
    "qwen3": 131072,
    "mistral": 32768,
    "mixtral": 32768,
    "phi-3": 131072,
    "phi3": 131072,
    "gemma-2": 8192,
    "gemma2": 8192,
    "gemma-3": 131072,
    "deepseek": 65536,
    "yi": 200000,
    "command-r": 131072,
}


def extract_param_count(name: str, tags: Iterable[str] | None = None) -> str:
    """Return a human-readable parameter string like '7B', '1.5B', '8x7B'."""
    sources = [name] + list(tags or [])
    for s in sources:
        m = _MOE_RE.search(s)
        if m:
            return f"{m.group(1)}x{m.group(2)}B"

    for s in sources:
        m = _PARAM_B_RE.search(s)
        if m:
            return f"{m.group(1)}B"

    for s in sources:
        m = _PARAM_M_RE.search(s)
        if m:
            return f"{m.group(1)}M"

    return ""


def infer_use_case(name: str, tags: Iterable[str] | None = None) -> str:
    """Guess Nameweaver use_case enum value from name + HF tags."""
    n = name.lower()
    tag_str = " ".join(t.lower() for t in (tags or []))
    blob = f"{n} {tag_str}"

    if any(k in blob for k in ("embedding", "sentence-similarity", "feature-extraction", "bge", "-e5-")):
        return "embedding"
    if any(k in blob for k in ("vision", "vl", "image-text", "multimodal", "llava", "pixtral", "-vl")):
        return "multimodal"
    if any(k in blob for k in ("code", "coder", "starcoder", "codellama")):
        return "coding"
    if any(k in blob for k in ("reasoning", "-r1", "qwq", "thinking", "o1")):
        return "reasoning"
    if any(k in blob for k in ("instruct", "chat", "assistant", "-it")):
        return "chat"
    return "general"


def infer_capabilities(tags: Iterable[str] | None = None) -> list[str]:
    """Infer Nameweaver capabilities enum from HF tags."""
    if not tags:
        return []
    caps: set[str] = set()
    tag_set = {t.lower() for t in tags}
    if tag_set & {"vision", "image-text-to-text", "visual-question-answering"}:
        caps.add("vision")
    if tag_set & {"tool-use", "function-calling"}:
        caps.add("tool_use")
    return sorted(caps)


def infer_ctx_length(name: str, config: dict | None = None) -> int:
    """Infer context length from config.json or name patterns."""
    if config:
        for key in ("max_position_embeddings", "model_max_length", "sliding_window"):
            v = config.get(key)
            if isinstance(v, int) and v > 0:
                return v

    n = name.lower()
    m = _CTX_K_RE.search(n)
    if m:
        return int(m.group(1)) * 1024

    for family, ctx in _CTX_DEFAULTS.items():
        if family in n:
            return ctx

    return 4096


def estimate_memory_gb(params_b: float, quant: str = "Q4_K_M") -> tuple[float, float]:
    """Return (ram_gb, vram_gb) for the given param count under ``quant``.

    Follows the llmfit heuristic: weight_gb ≈ params_b * bpp, then add ~1GB
    for runtime + small KV overhead. VRAM tracks weight; RAM is weight + 2GB.
    """
    from models import QUANT_BPP

    bpp = QUANT_BPP.get(quant, 0.5)
    weight_gb = params_b * bpp
    vram_gb = round(weight_gb + 1.0, 1)
    ram_gb = round(weight_gb + 2.0, 1)
    return ram_gb, vram_gb


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _build_request(url: str, token: str = "") -> urllib.request.Request:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _http_json(url: str, token: str = "", timeout: float = 10.0) -> object | None:
    """GET URL and return parsed JSON, or None on failure.

    Auth/rate-limit failures (401/403/429) are warned so the UI log shows a
    likely cause when the catalog comes back empty.
    """
    ctx = ssl.create_default_context()
    try:
        req = _build_request(url, token)
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            logger.warning("HF auth failed (%d) — check your HF token: %s", exc.code, url)
        elif exc.code == 429:
            logger.warning("HF rate limit hit (429): %s", url)
        else:
            logger.debug("HF HTTP %d: %s", exc.code, url)
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.debug("HF request failed: %s — %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# HuggingFace API client
# ---------------------------------------------------------------------------


class HuggingFaceAPI:
    """Thin client for the public HF models API."""

    def __init__(self, token: str = "", timeout: float = 10.0):
        self.token = token
        self.timeout = timeout

    # ---- Low-level endpoints ----

    def search_models(self, query: str, limit: int = 50) -> list[dict]:
        params = {
            "search": query,
            "pipeline_tag": "text-generation",
            "sort": "downloads",
            "direction": "-1",
            "limit": str(limit),
        }
        url = f"{HF_API}/models?{urllib.parse.urlencode(params)}"
        data = _http_json(url, self.token, self.timeout)
        return data if isinstance(data, list) else []

    def fetch_trending(self, limit: int = 100, pipeline: str = "text-generation") -> list[dict]:
        params = {
            "pipeline_tag": pipeline,
            "sort": "trendingScore",
            "direction": "-1",
            "limit": str(limit),
        }
        url = f"{HF_API}/models?{urllib.parse.urlencode(params)}"
        data = _http_json(url, self.token, self.timeout)
        return data if isinstance(data, list) else []

    def fetch_popular(self, limit: int = 200, pipeline: str = "text-generation") -> list[dict]:
        params = {
            "pipeline_tag": pipeline,
            "sort": "downloads",
            "direction": "-1",
            "limit": str(limit),
        }
        url = f"{HF_API}/models?{urllib.parse.urlencode(params)}"
        data = _http_json(url, self.token, self.timeout)
        return data if isinstance(data, list) else []

    def fetch_model_config(self, repo_id: str) -> dict | None:
        """Fetch config.json from the model repo main branch."""
        url = f"{HF_MODEL_BASE}/{repo_id}/resolve/main/config.json"
        data = _http_json(url, self.token, self.timeout)
        return data if isinstance(data, dict) else None

    # ---- Conversion ----

    def convert_to_llm_model(self, entry: dict, config: dict | None = None) -> LlmModel | None:
        """Convert an HF API entry to a Nameweaver LlmModel."""
        repo_id = entry.get("modelId") or entry.get("id") or ""
        if not repo_id or "/" not in repo_id:
            return None

        provider = repo_id.split("/")[0]
        display = repo_id.split("/")[-1]

        tags = entry.get("tags") or []
        param_str = extract_param_count(display, tags)
        if not param_str:
            # Too uncertain — skip
            return None

        # Compute params_b for memory estimate
        try:
            from models import LlmModel as _LM  # avoid circular at type level

            tmp = _LM(name=display, parameter_count=param_str)
            params_b = tmp.active_params_b() or tmp.params_b()
        except Exception:
            params_b = 0.0

        if params_b <= 0:
            return None

        ram_gb, vram_gb = estimate_memory_gb(params_b, "Q4_K_M")
        ctx = infer_ctx_length(display, config)
        use_case = infer_use_case(display, tags)
        caps = infer_capabilities(tags)

        # Detect MoE from name or config
        expert_count = 0
        active_experts = 0
        moe_match = _MOE_RE.search(display)
        if moe_match:
            expert_count = int(moe_match.group(1))
            active_experts = 2  # Common default
        if config:
            n_exp = config.get("num_local_experts") or config.get("num_experts")
            if isinstance(n_exp, int) and n_exp > 0:
                expert_count = n_exp
            n_act = config.get("num_experts_per_tok")
            if isinstance(n_act, int) and n_act > 0:
                active_experts = n_act

        # License + release date from entry
        license_ = ""
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("license:"):
                license_ = tag.split(":", 1)[1]
                break

        release_date = ""
        created = entry.get("createdAt") or entry.get("lastModified") or ""
        if isinstance(created, str) and len(created) >= 10:
            release_date = created[:10]

        # Config-derived fields
        n_layers = 0
        n_heads = 0
        hidden = 0
        vocab = 0
        if config:
            n_layers = int(config.get("num_hidden_layers") or 0)
            n_heads = int(config.get("num_attention_heads") or 0)
            hidden = int(config.get("hidden_size") or 0)
            vocab = int(config.get("vocab_size") or 0)

        return LlmModel(
            name=display,
            provider=provider,
            parameter_count=param_str,
            ram_gb=ram_gb,
            vram_gb=vram_gb,
            format="gguf",
            quantization="Q4_K_M",
            n_layers=n_layers,
            attention_heads=n_heads,
            hidden_dim=hidden,
            vocab_size=vocab,
            ctx_length=ctx,
            use_case=use_case,
            capabilities=caps,
            expert_count=expert_count,
            active_experts=active_experts,
            license=license_,
            release_date=release_date,
        )


# ---------------------------------------------------------------------------
# Cache persistence
# ---------------------------------------------------------------------------


def cache_path() -> Path:
    return config_dir() / "hf_cache.json"


def save_cache(models: list[LlmModel]) -> None:
    """Write the given models to the HF cache file."""
    path = cache_path()
    payload = {
        "version": CACHE_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "models": [asdict(m) for m in models],
    }
    try:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Saved %d models to HF cache: %s", len(models), path)
    except OSError as exc:
        logger.error("Failed to save HF cache: %s", exc)


def read_cache_meta() -> dict:
    """Return the cache header (version, updated_at, count) if present."""
    path = cache_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {
            "version": data.get("version"),
            "updated_at": data.get("updated_at"),
            "count": len(data.get("models", [])),
        }
    except (OSError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# High-level update pipeline
# ---------------------------------------------------------------------------


def update_catalog(
    token: str = "",
    limit: int = 200,
    fetch_config: bool = False,
    on_progress: Callable[[int, str], None] | None = None,
) -> list[LlmModel]:
    """Fetch popular + trending HF models and convert them.

    ``on_progress(pct, msg)`` is invoked at key stages. Does not write cache.
    """
    api = HuggingFaceAPI(token=token)

    def progress(pct: int, msg: str) -> None:
        logger.info("HF update: %d%% — %s", pct, msg)
        if on_progress:
            on_progress(pct, msg)

    progress(5, "Fetching popular models…")
    popular = api.fetch_popular(limit=limit)

    progress(30, "Fetching trending models…")
    trending = api.fetch_trending(limit=min(100, limit // 2))

    # Dedup by repo id
    seen_ids: set[str] = set()
    combined: list[dict] = []
    for entry in popular + trending:
        rid = (entry.get("modelId") or entry.get("id") or "").lower()
        if rid and rid not in seen_ids:
            seen_ids.add(rid)
            combined.append(entry)

    progress(55, f"Converting {len(combined)} entries…")
    converted: list[LlmModel] = []
    total = max(1, len(combined))
    for i, entry in enumerate(combined):
        config = None
        if fetch_config:
            rid = entry.get("modelId") or entry.get("id") or ""
            if rid:
                config = api.fetch_model_config(rid)
        model = api.convert_to_llm_model(entry, config)
        if model:
            converted.append(model)
        if i % max(1, total // 10) == 0:
            progress(55 + int(40 * i / total), f"Converted {i}/{total}")

    progress(100, f"Done: {len(converted)} models")
    return converted
