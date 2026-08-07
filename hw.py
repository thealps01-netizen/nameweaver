"""Hardware detection — CPU, RAM, GPU with VRAM, bandwidth lookup."""

import logging
import platform
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum

import psutil

logger = logging.getLogger(__name__)


class GpuBackend(str, Enum):
    CUDA = "cuda"
    METAL = "metal"
    ROCM = "rocm"
    VULKAN = "vulkan"
    SYCL = "sycl"
    ASCEND = "ascend"         # Huawei NPU
    CPU_ARM = "cpu_arm"       # ARM CPU fallback
    CPU_X86 = "cpu_x86"       # x86 CPU fallback
    CPU_ONLY = "cpu"          # Kept for backwards compatibility


@dataclass
class GpuInfo:
    """Information about a single GPU."""

    name: str = "Unknown GPU"
    vram_gb: float = 0.0
    backend: GpuBackend = GpuBackend.CPU_ONLY
    count: int = 1
    unified_memory: bool = False
    bandwidth_gbps: float = 0.0  # Per-GPU memory bandwidth
    vendor: str = ""             # "NVIDIA" | "AMD" | "Intel" | "Apple" | "Huawei"
    pci_id: str = ""             # lspci/WMI ID — for rocm-smi index mapping
    integrated: bool = False     # iGPU flag — default-disabled in mixed setups
    enabled: bool = True         # User selection (cfg.disabled_gpus overrides)


@dataclass
class SystemSpecs:
    """Complete system hardware specification."""

    total_ram_gb: float = 0.0
    available_ram_gb: float = 0.0
    cpu_name: str = "Unknown CPU"
    total_cpu_cores: int = 1
    has_gpu: bool = False
    gpu_name: str = ""
    gpu_vram_gb: float = 0.0
    total_gpu_vram_gb: float = 0.0
    gpu_count: int = 0
    gpu_backend: GpuBackend = GpuBackend.CPU_ONLY
    unified_memory: bool = False
    gpus: list[GpuInfo] = field(default_factory=list)
    gpu_bandwidth_gbps: float = 0.0

    @classmethod
    def detect(cls) -> "SystemSpecs":
        """Detect current system hardware. Safe to call from any thread."""
        specs = cls()
        _detect_cpu_ram(specs)
        _detect_gpu(specs)
        return specs

    def with_overrides(
        self,
        ram_gb: float | None = None,
        vram_gb: float | None = None,
        cpu_cores: int | None = None,
    ) -> "SystemSpecs":
        """Return a copy with overridden values (for hardware simulation)."""
        import copy

        s = copy.deepcopy(self)
        if ram_gb is not None:
            s.total_ram_gb = ram_gb
            s.available_ram_gb = ram_gb * 0.85
        if vram_gb is not None:
            s.gpu_vram_gb = vram_gb
            s.total_gpu_vram_gb = vram_gb * s.gpu_count if s.gpu_count > 0 else vram_gb
            s.has_gpu = vram_gb > 0
            for gpu in s.gpus:
                gpu.vram_gb = vram_gb
        if cpu_cores is not None:
            s.total_cpu_cores = cpu_cores
        return s


# ---------------------------------------------------------------------------
# GPU memory bandwidth lookup (GB/s) — from llmfit hardware.rs
# ---------------------------------------------------------------------------

GPU_BANDWIDTH_TABLE: dict[str, float] = {
    # NVIDIA Consumer
    "rtx 4090": 1008.0,
    "rtx 4080 super": 736.0,
    "rtx 4080": 716.8,
    "rtx 4070 ti super": 672.0,
    "rtx 4070 ti": 504.0,
    "rtx 4070 super": 504.0,
    "rtx 4070": 504.0,
    "rtx 4060 ti": 288.0,
    "rtx 4060": 272.0,
    "rtx 3090 ti": 1008.0,
    "rtx 3090": 936.0,
    "rtx 3080 ti": 912.0,
    "rtx 3080": 760.0,
    "rtx 3070 ti": 608.0,
    "rtx 3070": 448.0,
    "rtx 3060 ti": 448.0,
    "rtx 3060": 360.0,
    "rtx 2080 ti": 616.0,
    "rtx 2080 super": 496.0,
    "rtx 2080": 448.0,
    "rtx 2070 super": 448.0,
    "rtx 2070": 448.0,
    "rtx 2060 super": 448.0,
    "rtx 2060": 336.0,
    # NVIDIA Data Center
    "a100 80gb": 2039.0,
    "a100 40gb": 1555.0,
    "a100": 1555.0,
    "h100": 3350.0,
    "h200": 4800.0,
    "l40s": 864.0,
    "l40": 864.0,
    "l4": 300.0,
    "a6000": 768.0,
    "a5000": 768.0,
    "a4000": 448.0,
    "rtx 6000 ada": 960.0,
    "rtx 5000 ada": 768.0,
    "rtx 4000 ada": 400.0,
    # NVIDIA RTX 50 series
    "rtx 5090": 1792.0,
    "rtx 5080": 960.0,
    "rtx 5070 ti": 896.0,
    "rtx 5070": 672.0,
    # AMD RDNA 4
    "rx 9070 xt": 624.0,
    "rx 9070": 540.0,
    # AMD RDNA 3
    "rx 7900 xtx": 960.0,
    "rx 7900 xt": 800.0,
    "rx 7900 gre": 576.0,
    "rx 7800 xt": 624.0,
    "rx 7700 xt": 432.0,
    "rx 7600 xt": 288.0,
    "rx 7600": 288.0,
    # AMD Data Center
    "mi300x": 5300.0,
    "mi250x": 3276.0,
    "mi210": 1638.0,
    # Apple Silicon
    "m1": 68.25,
    "m1 pro": 200.0,
    "m1 max": 400.0,
    "m1 ultra": 800.0,
    "m2": 100.0,
    "m2 pro": 200.0,
    "m2 max": 400.0,
    "m2 ultra": 800.0,
    "m3": 100.0,
    "m3 pro": 150.0,
    "m3 max": 400.0,
    "m3 ultra": 800.0,
    "m4": 120.0,
    "m4 pro": 273.0,
    "m4 max": 546.0,
    "m4 ultra": 819.0,
    # Intel Arc
    "arc a770": 560.0,
    "arc a750": 512.0,
    "arc a580": 512.0,
    "arc b580": 456.0,
}


def _lookup_bandwidth(gpu_name: str) -> float:
    """Look up GPU memory bandwidth from the table."""
    name_lower = gpu_name.lower()
    for key, bw in GPU_BANDWIDTH_TABLE.items():
        if key in name_lower:
            return bw
    return 0.0


# Known VRAM sizes (GB) for GPUs where WMI often reports incorrectly
# WMI/Win32_VideoController.AdapterRAM is a 32-bit DWORD, so any GPU
# with >4 GB VRAM gets truncated (e.g. 16 GB → 4 GB, 12 GB → 4 GB).
GPU_KNOWN_VRAM: dict[str, float] = {
    # NVIDIA
    "rtx 5090": 32.0,
    "rtx 5080": 16.0,
    "rtx 5070 ti": 16.0,
    "rtx 5070": 12.0,
    "rtx 4090": 24.0,
    "rtx 4080 super": 16.0,
    "rtx 4080": 16.0,
    "rtx 4070 ti super": 16.0,
    "rtx 4070 ti": 12.0,
    "rtx 4070 super": 12.0,
    "rtx 4070": 12.0,
    "rtx 4060 ti 16": 16.0,
    "rtx 4060 ti": 8.0,
    "rtx 4060": 8.0,
    "rtx 3090 ti": 24.0,
    "rtx 3090": 24.0,
    "rtx 3080 ti": 12.0,
    "rtx 3080": 10.0,
    "rtx 3070 ti": 8.0,
    "rtx 3070": 8.0,
    "rtx 3060 ti": 8.0,
    "rtx 3060": 12.0,
    # AMD RDNA 4
    "rx 9070 xt": 16.0,
    "rx 9070": 12.0,
    # AMD RDNA 3
    "rx 7900 xtx": 24.0,
    "rx 7900 xt": 20.0,
    "rx 7900 gre": 16.0,
    "rx 7800 xt": 16.0,
    "rx 7700 xt": 12.0,
    "rx 7600 xt": 16.0,
    "rx 7600": 8.0,
    # AMD RDNA 2
    "rx 6950 xt": 16.0,
    "rx 6900 xt": 16.0,
    "rx 6800 xt": 16.0,
    "rx 6800": 16.0,
    "rx 6700 xt": 12.0,
    "rx 6600 xt": 8.0,
    "rx 6600": 8.0,
    # Intel Arc
    "arc a770": 16.0,
    "arc a750": 8.0,
    "arc b580": 12.0,
    # Data center
    "a100 80gb": 80.0,
    "a100 40gb": 40.0,
    "a100": 40.0,
    "h100": 80.0,
    "h200": 141.0,
    "l40s": 48.0,
    "l40": 48.0,
    "a6000": 48.0,
    "a5000": 24.0,
}


def _lookup_known_vram(gpu_name: str) -> float | None:
    """Look up known VRAM size from a curated table. Returns None if unknown."""
    name_lower = gpu_name.lower()
    for key, vram in GPU_KNOWN_VRAM.items():
        if key in name_lower:
            return vram
    return None


def _is_integrated_gpu(name: str) -> bool:
    """Heuristic: detect integrated/iGPU names to deprioritize them."""
    n = name.lower()
    # Generic "AMD Radeon Graphics" (no RX/PRO) = Ryzen iGPU
    if "radeon" in n and "graphics" in n and "rx" not in n and "pro" not in n:
        return True
    # Intel UHD/Iris/HD Graphics
    if any(tag in n for tag in ("intel uhd", "intel iris", "intel hd", "intel(r) uhd", "intel(r) iris")):
        return True
    # Microsoft Basic Display
    if "basic display" in n or "microsoft" in n:
        return True
    return False


def _classify_vendor_backend(name: str) -> tuple[str, GpuBackend]:
    """Infer (vendor, backend) from a GPU name string."""
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "rtx" in n or "gtx" in n or "tesla" in n or "quadro" in n:
        return "NVIDIA", GpuBackend.CUDA
    if "intel" in n and ("arc" in n or "a770" in n or "a750" in n or "b580" in n or "a580" in n):
        return "Intel", GpuBackend.SYCL
    if "intel" in n:
        # Intel integrated (Iris, UHD, HD) — Vulkan is more widely supported than SYCL for iGPU
        return "Intel", GpuBackend.VULKAN
    if "amd" in n or "radeon" in n or "instinct" in n or "mi300" in n or "mi250" in n or "mi210" in n:
        return "AMD", GpuBackend.ROCM
    if "ascend" in n or "huawei" in n:
        return "Huawei", GpuBackend.ASCEND
    if "apple" in n or "m1" in n or "m2" in n or "m3" in n or "m4" in n:
        return "Apple", GpuBackend.METAL
    return "", GpuBackend.VULKAN


def _select_primary(gpus: list["GpuInfo"]) -> "GpuInfo | None":
    """Pick the primary GPU: discrete > integrated; ties broken by VRAM."""
    if not gpus:
        return None
    enabled = [g for g in gpus if g.enabled] or gpus
    discrete = [g for g in enabled if not g.integrated]
    pool = discrete or enabled
    return max(pool, key=lambda g: (g.vram_gb, g.bandwidth_gbps))


def enabled_gpus(specs: "SystemSpecs") -> list["GpuInfo"]:
    """Return only GPUs the user hasn't disabled."""
    return [g for g in specs.gpus if g.enabled]


def enabled_vram_gb(specs: "SystemSpecs") -> float:
    """Sum of VRAM across user-enabled GPUs."""
    return sum(g.vram_gb for g in specs.gpus if g.enabled)


def effective_bandwidth_gbps(specs: "SystemSpecs") -> float:
    """Dominant bandwidth for inference — the max across enabled GPUs.

    Parallel inference is usually bottlenecked by the slowest step, but in
    single-model-per-GPU setups the fastest card's bandwidth is what matters.
    """
    enabled = [g.bandwidth_gbps for g in specs.gpus if g.enabled and g.bandwidth_gbps > 0]
    if enabled:
        return max(enabled)
    return specs.gpu_bandwidth_gbps  # Fallback to pre-computed primary


def has_mixed_backends(specs: "SystemSpecs") -> bool:
    """True if the system has GPUs from >1 distinct backend (excludes CPU-only)."""
    backends = {g.backend for g in specs.gpus if g.backend != GpuBackend.CPU_ONLY}
    return len(backends) > 1


def apply_disabled_list(specs: "SystemSpecs", disabled_names: list[str]) -> None:
    """Mark GPUs as disabled based on a persisted name list. Mutates specs in-place."""
    disabled_set = set(disabled_names or [])
    for g in specs.gpus:
        g.enabled = g.name not in disabled_set


# ---------------------------------------------------------------------------
# CPU / RAM detection
# ---------------------------------------------------------------------------


def _detect_cpu_ram(specs: SystemSpecs) -> None:
    """Detect CPU name, core count, and RAM using psutil."""
    try:
        mem = psutil.virtual_memory()
        specs.total_ram_gb = round(mem.total / (1024**3), 1)
        specs.available_ram_gb = round(mem.available / (1024**3), 1)
    except Exception as exc:
        logger.warning("Failed to detect RAM: %s", exc)

    specs.total_cpu_cores = psutil.cpu_count(logical=True) or 1

    # CPU name
    try:
        if platform.system() == "Windows":
            specs.cpu_name = platform.processor() or "Unknown CPU"
            # Try to get a better name via PowerShell
            try:
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_Processor).Name"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if result.returncode == 0 and result.stdout.strip():
                    specs.cpu_name = result.stdout.strip()
            except Exception:
                # Fallback: wmic
                try:
                    result = subprocess.run(
                        ["wmic", "cpu", "get", "name"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                    if len(lines) >= 2:
                        specs.cpu_name = lines[1]
                except Exception:
                    pass
        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                specs.cpu_name = result.stdout.strip()
        else:
            # Linux
            try:
                with open("/proc/cpuinfo") as f:
                    for line in f:
                        if line.startswith("model name"):
                            specs.cpu_name = line.split(":", 1)[1].strip()
                            break
            except OSError:
                specs.cpu_name = platform.processor() or "Unknown CPU"
    except Exception as exc:
        logger.debug("CPU name detection failed: %s", exc)


# ---------------------------------------------------------------------------
# GPU detection
# ---------------------------------------------------------------------------


def _detect_gpu(specs: SystemSpecs) -> None:
    """Detect GPU(s) — tries NVIDIA first, then platform fallbacks."""
    # Try NVIDIA first
    if _detect_nvidia(specs):
        return

    # Platform-specific fallbacks
    if platform.system() == "Darwin":
        _detect_apple_silicon(specs)
    elif platform.system() == "Windows":
        _detect_windows_gpu(specs)
    elif platform.system() == "Linux":
        _detect_linux_gpu(specs)


def _compute_nvidia_bandwidth_gbps(bus_width_bits: float, mem_clock_mhz: float) -> float:
    """Compute theoretical NVIDIA VRAM bandwidth from bus width + clock.

    Formula (GDDR6/6X): bandwidth = (bus_width_bits * mem_clock_MHz * 2 DDR) / 8
    Result in GB/s. Returns 0.0 if inputs are invalid.

    Real-world bandwidth is typically 85-95% of this theoretical peak, but
    the per-card lookup table already encodes the manufacturer spec which
    matches this formula. Use this when the GPU isn't in the lookup table
    or the user has over/underclocked memory.
    """
    if bus_width_bits <= 0 or mem_clock_mhz <= 0:
        return 0.0
    # DDR = data rate 2× clock; divide bits→bytes by 8
    # Bandwidth = bus_width * mem_clock * 2 / 8  (MB/s) → /1000 for GB/s
    return round(bus_width_bits * mem_clock_mhz * 2 / 8 / 1000.0, 1)


def _query_nvidia_bandwidth(count: int) -> list[float]:
    """Query nvidia-smi for per-GPU memory bus width and clock.

    Returns a list of bandwidths (GB/s), one per detected GPU, aligned
    with the same order as the primary nvidia-smi query. Empty list on
    failure — caller falls back to lookup table.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.bus_width,clocks.max.memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW
            if platform.system() == "Windows"
            else 0,
        )
        if result.returncode != 0:
            return []
        out: list[float] = []
        for line in result.stdout.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                try:
                    bus_width = float(parts[0])
                    mem_clock = float(parts[1])
                    out.append(_compute_nvidia_bandwidth_gbps(bus_width, mem_clock))
                except ValueError:
                    out.append(0.0)
        return out[:count] if count else out
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        logger.debug("nvidia-smi bandwidth query failed: %s", exc)
        return []


def _detect_nvidia(specs: SystemSpecs) -> bool:
    """Detect NVIDIA GPUs via nvidia-smi."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW
            if platform.system() == "Windows"
            else 0,
        )
        if result.returncode != 0:
            return False

        gpus = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                name = parts[0].strip()
                try:
                    vram_mb = float(parts[1].strip())
                    vram_gb = round(vram_mb / 1024, 1)
                except ValueError:
                    vram_gb = 0.0
                gpus.append(
                    GpuInfo(
                        name=name,
                        vram_gb=vram_gb,
                        backend=GpuBackend.CUDA,
                        count=1,
                        bandwidth_gbps=_lookup_bandwidth(name),
                        vendor="NVIDIA",
                    )
                )

        if gpus:
            # Enrich with measured bandwidth (covers OC/underclock + unknown cards)
            measured = _query_nvidia_bandwidth(len(gpus))
            for i, gpu in enumerate(gpus):
                if i < len(measured) and measured[i] > 0:
                    # Prefer measured when lookup is zero, OR when measured
                    # differs by >5% (user likely has over/underclocked).
                    table_bw = gpu.bandwidth_gbps
                    if table_bw <= 0 or abs(measured[i] - table_bw) / table_bw > 0.05:
                        logger.debug(
                            "GPU %d (%s) bandwidth: table=%.1f, measured=%.1f — using measured",
                            i, gpu.name, table_bw, measured[i],
                        )
                        gpu.bandwidth_gbps = measured[i]

            specs.gpus = gpus
            specs.has_gpu = True
            specs.gpu_backend = GpuBackend.CUDA
            specs.gpu_name = gpus[0].name
            specs.gpu_vram_gb = gpus[0].vram_gb
            specs.gpu_count = len(gpus)
            specs.total_gpu_vram_gb = sum(g.vram_gb for g in gpus)
            specs.gpu_bandwidth_gbps = gpus[0].bandwidth_gbps or _lookup_bandwidth(gpus[0].name)
            return True

    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.debug("nvidia-smi failed: %s", exc)

    return False


def _detect_apple_silicon(specs: SystemSpecs) -> None:
    """Detect Apple Silicon GPU (unified memory)."""
    if platform.processor() not in ("arm", ""):
        cpu_brand = specs.cpu_name.lower()
        if "apple" not in cpu_brand and "m1" not in cpu_brand and "m2" not in cpu_brand:
            return

    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            total_bytes = int(result.stdout.strip())
            total_gb = round(total_bytes / (1024**3), 1)
            # Apple Silicon shares RAM with GPU — ~75% usable as VRAM
            gpu_vram = round(total_gb * 0.75, 1)

            # Determine chip name
            chip_name = "Apple Silicon"
            try:
                chip_result = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if chip_result.returncode == 0:
                    chip_name = chip_result.stdout.strip()
            except Exception:
                pass

            gpu = GpuInfo(
                name=chip_name,
                vram_gb=gpu_vram,
                backend=GpuBackend.METAL,
                count=1,
                unified_memory=True,
                bandwidth_gbps=_lookup_bandwidth(chip_name),
                vendor="Apple",
            )
            specs.gpus = [gpu]
            specs.has_gpu = True
            specs.gpu_backend = GpuBackend.METAL
            specs.gpu_name = chip_name
            specs.gpu_vram_gb = gpu_vram
            specs.total_gpu_vram_gb = gpu_vram
            specs.gpu_count = 1
            specs.unified_memory = True
            specs.gpu_bandwidth_gbps = _lookup_bandwidth(chip_name)
    except Exception as exc:
        logger.debug("Apple Silicon detection failed: %s", exc)


def _detect_windows_gpu(specs: SystemSpecs) -> None:
    """Detect GPU on Windows via PowerShell CIM (preferred) or wmic fallback.

    Handles two common WMI issues:
    1. AdapterRAM is a 32-bit DWORD — any GPU with >4 GB VRAM gets truncated.
       We override with a curated lookup table (GPU_KNOWN_VRAM).
    2. Integrated GPUs (Ryzen iGPU, Intel UHD) appear first. We sort so that
       dedicated GPUs are preferred as the primary GPU.
    """
    raw_gpus: list[GpuInfo] = []

    # --- PowerShell Get-CimInstance ---
    try:
        ps_cmd = (
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name, AdapterRAM | "
            "ForEach-Object { $_.Name + '|' + $_.AdapterRAM }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if "|" not in line:
                    continue
                parts = line.split("|", 1)
                name = parts[0].strip()
                if not name:
                    continue
                try:
                    adapter_ram = int(parts[1].strip()) if parts[1].strip() else 0
                    wmi_vram_gb = round(adapter_ram / (1024**3), 1)
                except (ValueError, IndexError):
                    wmi_vram_gb = 0.0

                # Use known VRAM table to correct WMI's 32-bit truncation
                known_vram = _lookup_known_vram(name)
                vram_gb = known_vram if known_vram is not None else wmi_vram_gb
                if known_vram is not None and known_vram != wmi_vram_gb:
                    logger.debug(
                        "Corrected VRAM for %s: WMI=%.1f GB -> known=%.1f GB",
                        name, wmi_vram_gb, known_vram,
                    )

                # Detect vendor + backend from name (handles Intel Arc, Ascend, etc.)
                vendor, backend = _classify_vendor_backend(name)
                integrated = _is_integrated_gpu(name)
                raw_gpus.append(
                    GpuInfo(
                        name=name,
                        vram_gb=vram_gb,
                        backend=backend,
                        count=1,
                        bandwidth_gbps=_lookup_bandwidth(name),
                        vendor=vendor,
                        integrated=integrated,
                        enabled=not integrated,  # iGPUs default-disabled
                    )
                )
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.debug("PowerShell GPU detection failed: %s", exc)

    # --- Fallback: wmic ---
    if not raw_gpus:
        try:
            result = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name,AdapterRAM"],
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                for line in lines[1:]:
                    match = re.match(r"(\d+)\s+(.+)", line)
                    if match:
                        adapter_ram = int(match.group(1))
                        name = match.group(2).strip()
                        wmi_vram_gb = round(adapter_ram / (1024**3), 1)
                        known_vram = _lookup_known_vram(name)
                        vram_gb = known_vram if known_vram is not None else wmi_vram_gb

                        vendor, backend = _classify_vendor_backend(name)
                        integrated = _is_integrated_gpu(name)
                        raw_gpus.append(
                            GpuInfo(
                                name=name,
                                vram_gb=vram_gb,
                                backend=backend,
                                count=1,
                                bandwidth_gbps=_lookup_bandwidth(name),
                                vendor=vendor,
                                integrated=integrated,
                                enabled=not integrated,
                            )
                        )
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.debug("wmic GPU detection failed: %s", exc)

    if not raw_gpus:
        return

    # Sort: discrete first, integrated last — keep both so users can toggle iGPU
    discrete = [g for g in raw_gpus if not g.integrated]
    integrated = [g for g in raw_gpus if g.integrated]
    # If no discrete GPU, integrated becomes the default-enabled one
    if not discrete:
        for g in integrated:
            g.enabled = True
    specs.gpus = discrete + integrated

    specs.has_gpu = any(g.enabled and g.vram_gb > 0 for g in specs.gpus) or bool(specs.gpus)
    primary = _select_primary(specs.gpus) or specs.gpus[0]
    specs.gpu_name = primary.name
    specs.gpu_vram_gb = primary.vram_gb
    specs.gpu_count = len(specs.gpus)
    specs.total_gpu_vram_gb = sum(g.vram_gb for g in specs.gpus if g.enabled)
    specs.gpu_backend = primary.backend
    specs.gpu_bandwidth_gbps = primary.bandwidth_gbps or _lookup_bandwidth(primary.name)

    logger.info(
        "Detected %d GPU(s): %s",
        len(specs.gpus),
        ", ".join(
            f"{g.name} ({g.vram_gb:.1f} GB, {g.backend.value}{', iGPU' if g.integrated else ''})"
            for g in specs.gpus
        ),
    )


def _detect_linux_gpu(specs: SystemSpecs) -> None:
    """Detect GPU on Linux via lspci + rocm-smi / sysfs / npu-smi."""
    try:
        result = subprocess.run(
            ["lspci", "-nn"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return

        for line in result.stdout.split("\n"):
            if "VGA" in line or "3D" in line or "Display" in line:
                match = re.search(r":\s+(.+?)(?:\s+\[[\da-f]{4}:[\da-f]{4}\])?$", line)
                if match:
                    name = match.group(1).strip()
                    vendor, backend = _classify_vendor_backend(name)
                    integrated = _is_integrated_gpu(name)
                    # Known-VRAM fallback for common cards (lspci gives no VRAM)
                    vram_guess = _lookup_known_vram(name) or 0.0
                    gpu = GpuInfo(
                        name=name,
                        vram_gb=vram_guess,
                        backend=backend,
                        count=1,
                        bandwidth_gbps=_lookup_bandwidth(name),
                        vendor=vendor,
                        integrated=integrated,
                        enabled=not integrated,
                    )
                    specs.gpus.append(gpu)

        # Try ROCm for AMD VRAM (now handles multiple GPUs)
        if any(g.vendor == "AMD" for g in specs.gpus):
            _try_rocm_vram(specs)

        # Try Intel Arc sysfs for VRAM
        if any(g.vendor == "Intel" and not g.integrated for g in specs.gpus):
            _try_intel_arc_sysfs(specs)

        # Try Ascend NPU
        _detect_ascend(specs)

        if specs.gpus:
            if not any(g.enabled for g in specs.gpus):
                # Nothing discrete and no iGPU was enabled — flip iGPUs on
                for g in specs.gpus:
                    g.enabled = True
            specs.has_gpu = True
            primary = _select_primary(specs.gpus) or specs.gpus[0]
            specs.gpu_name = primary.name
            specs.gpu_vram_gb = primary.vram_gb
            specs.gpu_count = len(specs.gpus)
            specs.total_gpu_vram_gb = sum(g.vram_gb for g in specs.gpus if g.enabled)
            specs.gpu_backend = primary.backend
            specs.gpu_bandwidth_gbps = primary.bandwidth_gbps or _lookup_bandwidth(primary.name)
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.debug("Linux GPU detection failed: %s", exc)


def _try_rocm_vram(specs: SystemSpecs) -> None:
    """Get per-GPU AMD VRAM via `rocm-smi --showmeminfo vram`.

    Handles multi-GPU systems by matching ``GPU[<idx>]`` lines to the AMD
    GPUs already in ``specs.gpus`` in order.
    """
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return

        # rocm-smi output examples (one line per GPU, with index):
        #   GPU[0] : Total Memory (B): 25753026560
        #   GPU[1] : Total Memory (B): 17171480576
        pairs = re.findall(
            r"GPU\[(\d+)\][^\n]*?Total[^\d]*?(\d+)",
            result.stdout,
            re.IGNORECASE,
        )
        if not pairs:
            # Fallback: single-match for older rocm-smi formats
            m = re.search(r"Total.*?(\d+)", result.stdout)
            if m:
                pairs = [("0", m.group(1))]

        amd_gpus = [g for g in specs.gpus if g.vendor == "AMD"]
        for idx_str, bytes_str in pairs:
            idx = int(idx_str)
            if idx < len(amd_gpus):
                vram_bytes = int(bytes_str)
                # rocm-smi reports bytes in newer versions, MB in older
                if vram_bytes > 1024**3:
                    vram_gb = round(vram_bytes / (1024**3), 1)
                else:
                    vram_gb = round(vram_bytes / 1024, 1)
                amd_gpus[idx].vram_gb = vram_gb
                amd_gpus[idx].backend = GpuBackend.ROCM
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.debug("rocm-smi failed: %s", exc)


def _try_intel_arc_sysfs(specs: SystemSpecs) -> None:
    """Read Intel Arc VRAM from /sys/class/drm/cardX/device/mem_info_vram_total."""
    try:
        from pathlib import Path as _P
        import glob
        intel_gpus = [g for g in specs.gpus if g.vendor == "Intel" and not g.integrated]
        if not intel_gpus:
            return
        cards = sorted(glob.glob("/sys/class/drm/card*/device"))
        idx = 0
        for card in cards:
            try:
                vendor_path = _P(card) / "vendor"
                if not vendor_path.exists():
                    continue
                if vendor_path.read_text().strip() != "0x8086":
                    continue
                vram_path = _P(card) / "mem_info_vram_total"
                if vram_path.exists():
                    vram_bytes = int(vram_path.read_text().strip())
                    vram_gb = round(vram_bytes / (1024**3), 1)
                    if idx < len(intel_gpus):
                        intel_gpus[idx].vram_gb = vram_gb
                        idx += 1
            except (OSError, ValueError):
                continue
    except Exception as exc:
        logger.debug("Intel Arc sysfs read failed: %s", exc)


def _detect_ascend(specs: SystemSpecs) -> None:
    """Detect Huawei Ascend NPU via `npu-smi info`.

    Output format (abridged):
        +--------+--------+-----------------+
        | NPU    | Name   | Health          |
        +========+========+=================+
        | 0      | 910B   | OK              |
        +--------+--------+-----------------+
        HBM-Usage(MB): 0    / 65536
    """
    try:
        result = subprocess.run(
            ["npu-smi", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return

        # Parse rows: | <id> | <name> | <health> |
        row_pattern = re.compile(r"\|\s*(\d+)\s*\|\s*([^\|]+?)\s*\|")
        hbm_pattern = re.compile(r"HBM[-\s]?Usage\(MB\):\s*\d+\s*/\s*(\d+)", re.IGNORECASE)

        names_found = []
        for line in result.stdout.split("\n"):
            m = row_pattern.match(line.strip())
            if m and not m.group(2).lower().startswith(("name", "---")):
                names_found.append(m.group(2).strip())

        hbms = [int(x) for x in hbm_pattern.findall(result.stdout)]

        for idx, name in enumerate(names_found):
            vram_mb = hbms[idx] if idx < len(hbms) else 0
            vram_gb = round(vram_mb / 1024, 1) if vram_mb else 0.0
            display_name = f"Huawei Ascend {name}" if "ascend" not in name.lower() else name
            specs.gpus.append(
                GpuInfo(
                    name=display_name,
                    vram_gb=vram_gb,
                    backend=GpuBackend.ASCEND,
                    count=1,
                    bandwidth_gbps=_lookup_bandwidth(display_name),
                    vendor="Huawei",
                    integrated=False,
                    enabled=True,
                )
            )
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.debug("npu-smi failed: %s", exc)
