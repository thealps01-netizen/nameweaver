"""Shared test fixtures."""

import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hw import GpuBackend, GpuInfo, SystemSpecs
from models import LlmModel


@pytest.fixture
def sample_specs() -> SystemSpecs:
    """A typical gaming PC: i7, 32GB RAM, RTX 4090 24GB."""
    return SystemSpecs(
        total_ram_gb=32.0,
        available_ram_gb=28.0,
        cpu_name="Intel Core i7-13700K",
        total_cpu_cores=24,
        has_gpu=True,
        gpu_name="NVIDIA GeForce RTX 4090",
        gpu_vram_gb=24.0,
        total_gpu_vram_gb=24.0,
        gpu_count=1,
        gpu_backend=GpuBackend.CUDA,
        unified_memory=False,
        gpus=[
            GpuInfo(
                name="NVIDIA GeForce RTX 4090",
                vram_gb=24.0,
                backend=GpuBackend.CUDA,
                count=1,
            )
        ],
        gpu_bandwidth_gbps=1008.0,
    )


@pytest.fixture
def low_end_specs() -> SystemSpecs:
    """A low-end system: 8GB RAM, no GPU."""
    return SystemSpecs(
        total_ram_gb=8.0,
        available_ram_gb=6.0,
        cpu_name="Intel Core i5-8250U",
        total_cpu_cores=8,
        has_gpu=False,
        gpu_name="",
        gpu_vram_gb=0.0,
        total_gpu_vram_gb=0.0,
        gpu_count=0,
        gpu_backend=GpuBackend.CPU_ONLY,
    )


@pytest.fixture
def small_model() -> LlmModel:
    """A small 3B model."""
    return LlmModel(
        name="TestModel-3B",
        provider="test",
        parameter_count="3B",
        ram_gb=3.5,
        vram_gb=2.5,
        format="gguf",
        quantization="Q4_K_M",
        n_layers=28,
        attention_heads=24,
        hidden_dim=3072,
        ctx_length=4096,
        use_case="general",
    )


@pytest.fixture
def large_model() -> LlmModel:
    """A large 70B model."""
    return LlmModel(
        name="TestModel-70B",
        provider="test",
        parameter_count="70B",
        ram_gb=40.0,
        vram_gb=38.0,
        format="gguf",
        quantization="Q4_K_M",
        n_layers=80,
        attention_heads=64,
        hidden_dim=8192,
        ctx_length=131072,
        use_case="general",
    )


@pytest.fixture
def dual_nvidia_specs() -> SystemSpecs:
    """2× RTX 4090 — dual-GPU NVIDIA workstation, 48 GB total VRAM."""
    gpus = [
        GpuInfo(
            name="NVIDIA GeForce RTX 4090",
            vram_gb=24.0,
            backend=GpuBackend.CUDA,
            bandwidth_gbps=1008.0,
            vendor="NVIDIA",
            enabled=True,
        ),
        GpuInfo(
            name="NVIDIA GeForce RTX 4090",
            vram_gb=24.0,
            backend=GpuBackend.CUDA,
            bandwidth_gbps=1008.0,
            vendor="NVIDIA",
            enabled=True,
        ),
    ]
    return SystemSpecs(
        total_ram_gb=64.0,
        available_ram_gb=56.0,
        cpu_name="AMD Threadripper 7960X",
        total_cpu_cores=48,
        has_gpu=True,
        gpu_name=gpus[0].name,
        gpu_vram_gb=24.0,
        total_gpu_vram_gb=48.0,
        gpu_count=2,
        gpu_backend=GpuBackend.CUDA,
        gpus=gpus,
        gpu_bandwidth_gbps=1008.0,
    )


@pytest.fixture
def amd_dual_specs() -> SystemSpecs:
    """2× RX 7900 XTX — dual-AMD, ROCm."""
    gpus = [
        GpuInfo(
            name="AMD Radeon RX 7900 XTX",
            vram_gb=24.0,
            backend=GpuBackend.ROCM,
            bandwidth_gbps=960.0,
            vendor="AMD",
            enabled=True,
        ),
        GpuInfo(
            name="AMD Radeon RX 7900 XTX",
            vram_gb=24.0,
            backend=GpuBackend.ROCM,
            bandwidth_gbps=960.0,
            vendor="AMD",
            enabled=True,
        ),
    ]
    return SystemSpecs(
        total_ram_gb=32.0,
        available_ram_gb=28.0,
        cpu_name="AMD Ryzen 9 7950X",
        total_cpu_cores=32,
        has_gpu=True,
        gpu_name=gpus[0].name,
        gpu_vram_gb=24.0,
        total_gpu_vram_gb=48.0,
        gpu_count=2,
        gpu_backend=GpuBackend.ROCM,
        gpus=gpus,
        gpu_bandwidth_gbps=960.0,
    )


@pytest.fixture
def mixed_backend_specs() -> SystemSpecs:
    """RTX 4090 + Intel Iris Xe iGPU — iGPU disabled by default."""
    gpus = [
        GpuInfo(
            name="NVIDIA GeForce RTX 4090",
            vram_gb=24.0,
            backend=GpuBackend.CUDA,
            bandwidth_gbps=1008.0,
            vendor="NVIDIA",
            integrated=False,
            enabled=True,
        ),
        GpuInfo(
            name="Intel Iris Xe Graphics",
            vram_gb=0.0,
            backend=GpuBackend.VULKAN,
            bandwidth_gbps=0.0,
            vendor="Intel",
            integrated=True,
            enabled=False,
        ),
    ]
    return SystemSpecs(
        total_ram_gb=32.0,
        available_ram_gb=28.0,
        cpu_name="Intel Core i9-13900HX",
        total_cpu_cores=32,
        has_gpu=True,
        gpu_name=gpus[0].name,
        gpu_vram_gb=24.0,
        total_gpu_vram_gb=24.0,  # iGPU excluded
        gpu_count=2,
        gpu_backend=GpuBackend.CUDA,
        gpus=gpus,
        gpu_bandwidth_gbps=1008.0,
    )


@pytest.fixture
def ascend_specs() -> SystemSpecs:
    """Huawei Ascend 910B — 64 GB HBM."""
    gpus = [
        GpuInfo(
            name="Huawei Ascend 910B",
            vram_gb=64.0,
            backend=GpuBackend.ASCEND,
            bandwidth_gbps=0.0,
            vendor="Huawei",
            enabled=True,
        ),
    ]
    return SystemSpecs(
        total_ram_gb=128.0,
        available_ram_gb=120.0,
        cpu_name="Kunpeng 920",
        total_cpu_cores=64,
        has_gpu=True,
        gpu_name=gpus[0].name,
        gpu_vram_gb=64.0,
        total_gpu_vram_gb=64.0,
        gpu_count=1,
        gpu_backend=GpuBackend.ASCEND,
        gpus=gpus,
    )


@pytest.fixture
def moe_model() -> LlmModel:
    """A MoE model."""
    return LlmModel(
        name="TestMoE-8x7B",
        provider="test",
        parameter_count="8x7B",
        ram_gb=48.0,
        vram_gb=26.0,
        format="gguf",
        quantization="Q4_K_M",
        n_layers=32,
        attention_heads=32,
        hidden_dim=4096,
        ctx_length=32768,
        use_case="general",
        expert_count=8,
        active_experts=2,
    )
