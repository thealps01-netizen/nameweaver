"""Tests for hardware detection."""

from unittest.mock import MagicMock, patch

from hw import (
    GpuBackend,
    GpuInfo,
    SystemSpecs,
    _classify_vendor_backend,
    _detect_ascend,
    _lookup_bandwidth,
    _select_primary,
    _try_rocm_vram,
    apply_disabled_list,
    effective_bandwidth_gbps,
    enabled_gpus,
    enabled_vram_gb,
    has_mixed_backends,
)


class TestSystemSpecs:
    def test_detect_returns_specs(self):
        specs = SystemSpecs.detect()
        assert specs.total_ram_gb > 0
        assert specs.total_cpu_cores > 0
        assert specs.cpu_name != ""

    def test_with_overrides_ram(self, sample_specs):
        modified = sample_specs.with_overrides(ram_gb=64.0)
        assert modified.total_ram_gb == 64.0
        assert sample_specs.total_ram_gb == 32.0  # Original unchanged

    def test_with_overrides_vram(self, sample_specs):
        modified = sample_specs.with_overrides(vram_gb=48.0)
        assert modified.gpu_vram_gb == 48.0
        assert modified.has_gpu is True

    def test_with_overrides_cpu(self, sample_specs):
        modified = sample_specs.with_overrides(cpu_cores=64)
        assert modified.total_cpu_cores == 64

    def test_with_overrides_zero_vram(self, sample_specs):
        modified = sample_specs.with_overrides(vram_gb=0.0)
        assert modified.has_gpu is False

    def test_with_overrides_independent(self, sample_specs):
        """Ensure overrides don't leak between copies."""
        m1 = sample_specs.with_overrides(ram_gb=64.0)
        m2 = sample_specs.with_overrides(ram_gb=128.0)
        assert m1.total_ram_gb == 64.0
        assert m2.total_ram_gb == 128.0


class TestBandwidthLookup:
    def test_rtx_4090(self):
        bw = _lookup_bandwidth("NVIDIA GeForce RTX 4090")
        assert bw == 1008.0

    def test_rtx_3060(self):
        bw = _lookup_bandwidth("NVIDIA GeForce RTX 3060")
        assert bw == 360.0

    def test_unknown_gpu(self):
        bw = _lookup_bandwidth("Unknown GPU XYZ")
        assert bw == 0.0

    def test_case_insensitive(self):
        bw = _lookup_bandwidth("nvidia geforce RTX 4090")
        assert bw == 1008.0

    def test_apple_m1(self):
        bw = _lookup_bandwidth("Apple M1")
        assert bw > 0


class TestClassifyVendorBackend:
    def test_nvidia_rtx(self):
        vendor, backend = _classify_vendor_backend("NVIDIA GeForce RTX 4090")
        assert vendor == "NVIDIA"
        assert backend == GpuBackend.CUDA

    def test_intel_arc(self):
        vendor, backend = _classify_vendor_backend("Intel(R) Arc(TM) A770 Graphics")
        assert vendor == "Intel"
        assert backend == GpuBackend.SYCL

    def test_intel_iris_xe(self):
        vendor, backend = _classify_vendor_backend("Intel(R) Iris(R) Xe Graphics")
        assert vendor == "Intel"
        assert backend == GpuBackend.VULKAN  # iGPU — not SYCL

    def test_amd_radeon(self):
        vendor, backend = _classify_vendor_backend("AMD Radeon RX 7900 XTX")
        assert vendor == "AMD"
        assert backend == GpuBackend.ROCM

    def test_ascend(self):
        vendor, backend = _classify_vendor_backend("Huawei Ascend 910B")
        assert vendor == "Huawei"
        assert backend == GpuBackend.ASCEND

    def test_apple_m2(self):
        vendor, backend = _classify_vendor_backend("Apple M2 Max")
        assert vendor == "Apple"
        assert backend == GpuBackend.METAL

    def test_unknown_fallback(self):
        vendor, backend = _classify_vendor_backend("Mystery GPU 9000")
        assert vendor == ""
        assert backend == GpuBackend.VULKAN


class TestSelectPrimary:
    def test_discrete_beats_integrated(self):
        discrete = GpuInfo(name="RTX 4090", vram_gb=24.0, integrated=False)
        integrated = GpuInfo(name="Iris Xe", vram_gb=0.0, integrated=True)
        assert _select_primary([integrated, discrete]) is discrete

    def test_biggest_vram_wins_among_discrete(self):
        small = GpuInfo(name="RTX 3060", vram_gb=12.0, integrated=False, bandwidth_gbps=360)
        big = GpuInfo(name="RTX 4090", vram_gb=24.0, integrated=False, bandwidth_gbps=1008)
        assert _select_primary([small, big]) is big

    def test_empty_returns_none(self):
        assert _select_primary([]) is None

    def test_all_disabled_still_returns_one(self):
        g1 = GpuInfo(name="A", vram_gb=8.0, enabled=False)
        g2 = GpuInfo(name="B", vram_gb=16.0, enabled=False)
        # Falls back to full pool when nothing enabled
        assert _select_primary([g1, g2]) is g2


class TestEnabledHelpers:
    def test_enabled_gpus_filters(self, mixed_backend_specs):
        enabled = enabled_gpus(mixed_backend_specs)
        assert len(enabled) == 1
        assert enabled[0].vendor == "NVIDIA"

    def test_enabled_vram_sums_only_enabled(self, mixed_backend_specs):
        assert enabled_vram_gb(mixed_backend_specs) == 24.0

    def test_dual_nvidia_sums_vram(self, dual_nvidia_specs):
        assert enabled_vram_gb(dual_nvidia_specs) == 48.0

    def test_effective_bandwidth_is_max(self):
        specs = SystemSpecs()
        specs.gpus = [
            GpuInfo(name="A", vram_gb=8.0, bandwidth_gbps=300.0, enabled=True),
            GpuInfo(name="B", vram_gb=16.0, bandwidth_gbps=1000.0, enabled=True),
        ]
        assert effective_bandwidth_gbps(specs) == 1000.0

    def test_effective_bandwidth_skips_disabled(self):
        specs = SystemSpecs()
        specs.gpus = [
            GpuInfo(name="A", vram_gb=8.0, bandwidth_gbps=1500.0, enabled=False),
            GpuInfo(name="B", vram_gb=16.0, bandwidth_gbps=500.0, enabled=True),
        ]
        assert effective_bandwidth_gbps(specs) == 500.0

    def test_has_mixed_backends_true(self, mixed_backend_specs):
        assert has_mixed_backends(mixed_backend_specs) is True

    def test_has_mixed_backends_false(self, dual_nvidia_specs):
        assert has_mixed_backends(dual_nvidia_specs) is False

    def test_apply_disabled_list_marks_matching(self, dual_nvidia_specs):
        # Both cards share the same name — disabling by name disables both
        apply_disabled_list(dual_nvidia_specs, ["NVIDIA GeForce RTX 4090"])
        assert all(not g.enabled for g in dual_nvidia_specs.gpus)

    def test_apply_disabled_list_empty_enables_all(self, mixed_backend_specs):
        apply_disabled_list(mixed_backend_specs, [])
        assert all(g.enabled for g in mixed_backend_specs.gpus)


class TestRocmSmiMultiGpu:
    def _run_rocm(self, output: str, specs: SystemSpecs):
        """Helper: run _try_rocm_vram with mocked subprocess output."""
        with patch("hw.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output)
            _try_rocm_vram(specs)

    def test_parses_two_gpus(self):
        specs = SystemSpecs()
        specs.gpus = [
            GpuInfo(name="AMD Radeon RX 7900 XTX", vendor="AMD", backend=GpuBackend.VULKAN),
            GpuInfo(name="AMD Radeon RX 7900 XT", vendor="AMD", backend=GpuBackend.VULKAN),
        ]
        output = (
            "GPU[0]   : Total Memory (B): 25753026560\n"
            "GPU[1]   : Total Memory (B): 21474836480\n"
        )
        self._run_rocm(output, specs)
        assert specs.gpus[0].vram_gb == 24.0
        assert specs.gpus[1].vram_gb == 20.0
        assert specs.gpus[0].backend == GpuBackend.ROCM
        assert specs.gpus[1].backend == GpuBackend.ROCM

    def test_accepts_megabyte_format_legacy(self):
        specs = SystemSpecs()
        specs.gpus = [GpuInfo(name="AMD RX 6800 XT", vendor="AMD")]
        output = "GPU[0] : Total (MB): 16384\n"
        self._run_rocm(output, specs)
        # 16384 MB = 16.0 GB
        assert specs.gpus[0].vram_gb == 16.0

    def test_only_amd_gpus_affected(self):
        specs = SystemSpecs()
        specs.gpus = [
            GpuInfo(name="NVIDIA RTX 4090", vendor="NVIDIA", backend=GpuBackend.CUDA),
            GpuInfo(name="AMD Radeon Pro", vendor="AMD"),
        ]
        output = "GPU[0] : Total Memory (B): 17179869184\n"
        self._run_rocm(output, specs)
        # NVIDIA card untouched; AMD card gets 16 GB
        assert specs.gpus[0].backend == GpuBackend.CUDA
        assert specs.gpus[1].vram_gb == 16.0


class TestAscendDetection:
    def test_parses_single_ascend(self):
        specs = SystemSpecs()
        # Fake npu-smi info output
        output = """+-------+---------+-------+
| NPU   | Name    | Health|
+=======+=========+=======+
| 0     | 910B    | OK    |
+-------+---------+-------+
HBM-Usage(MB): 512    / 65536
"""
        with patch("hw.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output)
            _detect_ascend(specs)
        assert len(specs.gpus) == 1
        assert specs.gpus[0].backend == GpuBackend.ASCEND
        assert specs.gpus[0].vendor == "Huawei"
        assert specs.gpus[0].vram_gb == 64.0

    def test_missing_npu_smi_is_noop(self):
        specs = SystemSpecs()
        with patch("hw.subprocess.run", side_effect=FileNotFoundError):
            _detect_ascend(specs)
        assert specs.gpus == []
