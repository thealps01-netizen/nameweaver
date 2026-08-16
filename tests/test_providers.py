"""Tests for provider detection."""

from unittest.mock import patch

from providers import (
    ProviderState,
    ProviderStatus,
    detect_llamacpp,
    detect_ollama,
    detect_lm_studio,
    detect_docker_model_runner,
    _http_get_json,
)


class TestProviderStatus:
    def test_model_count(self):
        p = ProviderStatus(name="Test", available=True, installed_models={"a", "b", "c"})
        assert p.model_count == 3

    def test_empty_count(self):
        p = ProviderStatus(name="Test")
        assert p.model_count == 0

    def test_available_true_promotes_to_ready(self):
        """Legacy callers passing available=True should land in READY state."""
        p = ProviderStatus(name="Test", available=True)
        assert p.state == ProviderState.READY

    def test_state_ready_syncs_available(self):
        p = ProviderStatus(name="Test", state=ProviderState.READY)
        assert p.available is True

    def test_default_is_not_installed(self):
        p = ProviderStatus(name="Test")
        assert p.state == ProviderState.NOT_INSTALLED
        assert p.available is False


class TestHttpGetJson:
    def test_invalid_url(self):
        result = _http_get_json("http://localhost:99999/invalid", timeout=0.1)
        assert result is None

    def test_nonexistent_host(self):
        result = _http_get_json("http://192.0.2.1:1/test", timeout=0.1)
        assert result is None


class TestDetectOllama:
    @patch("providers._http_get_json")
    def test_ollama_available(self, mock_get):
        mock_get.return_value = {
            "models": [
                {"name": "llama3:latest"},
                {"name": "codellama:7b"},
            ]
        }
        status = detect_ollama()
        assert status.available is True
        assert status.state == ProviderState.READY
        assert status.model_count == 2
        assert "llama3:latest" in status.installed_models

    @patch("providers._ollama_is_installed")
    @patch("providers._http_get_json")
    def test_ollama_installed_but_off(self, mock_get, mock_installed):
        mock_get.return_value = None
        mock_installed.return_value = True
        status = detect_ollama()
        assert status.state == ProviderState.INSTALLED_OFF
        assert status.available is False
        assert status.start_action == "start_ollama"

    @patch("providers._ollama_is_installed")
    @patch("providers._http_get_json")
    def test_ollama_not_installed(self, mock_get, mock_installed):
        mock_get.return_value = None
        mock_installed.return_value = False
        status = detect_ollama()
        assert status.state == ProviderState.NOT_INSTALLED
        assert status.available is False
        assert status.install_hint  # URL populated


class TestDetectLmStudio:
    @patch("providers._scan_lmstudio_disk_models", return_value=set())
    @patch("providers._http_get_json")
    def test_lm_studio_available(self, mock_get, _mock_disk):
        mock_get.return_value = {
            "data": [{"id": "model-1"}, {"id": "model-2"}]
        }
        status = detect_lm_studio()
        assert status.available is True
        assert status.state == ProviderState.READY
        assert status.model_count == 2

    @patch("providers._scan_lmstudio_disk_models", return_value=set())
    @patch("providers._lmstudio_is_installed")
    @patch("providers._http_get_json")
    def test_lm_studio_installed_off(self, mock_get, mock_installed, _mock_disk):
        """Regression: Server mode off must not report 'not installed'."""
        mock_get.return_value = None
        mock_installed.return_value = True
        status = detect_lm_studio()
        assert status.state == ProviderState.INSTALLED_OFF
        assert status.start_action == "start_lmstudio"

    @patch("providers._scan_lmstudio_disk_models",
           return_value={"publisher/repo", "Model-Q4_K_M"})
    @patch("providers._lmstudio_is_installed", return_value=True)
    @patch("providers._http_get_json", return_value=None)
    def test_lm_studio_off_still_lists_disk_models(self, _g, _i, _disk):
        """Downloaded models remain visible even when the server is off."""
        status = detect_lm_studio()
        assert status.state == ProviderState.INSTALLED_OFF
        assert "publisher/repo" in status.installed_models
        assert "Model-Q4_K_M" in status.installed_models

    @patch("providers._lmstudio_is_installed")
    @patch("providers._http_get_json")
    def test_lm_studio_not_installed(self, mock_get, mock_installed):
        mock_get.return_value = None
        mock_installed.return_value = False
        status = detect_lm_studio()
        assert status.state == ProviderState.NOT_INSTALLED


class TestDetectLlamacpp:
    @patch("shutil.which")
    def test_found(self, mock_which):
        mock_which.side_effect = lambda x: "/usr/bin/llama-server" if x == "llama-server" else None
        status = detect_llamacpp()
        assert status.available is True
        assert status.state == ProviderState.READY

    @patch("shutil.which")
    def test_not_found(self, mock_which):
        mock_which.return_value = None
        status = detect_llamacpp()
        assert status.available is False
        assert status.state == ProviderState.NOT_INSTALLED


class TestDetectDockerModelRunner:
    @patch("providers._http_get_json")
    def test_running(self, mock_get):
        mock_get.return_value = {"data": [{"id": "ai/llama3"}]}
        status = detect_docker_model_runner()
        assert status.state == ProviderState.READY
        assert "ai/llama3" in status.installed_models

    @patch("providers._docker_is_installed")
    @patch("providers._http_get_json")
    def test_docker_installed_off(self, mock_get, mock_installed):
        mock_get.return_value = None
        mock_installed.return_value = True
        status = detect_docker_model_runner()
        assert status.state == ProviderState.INSTALLED_OFF

    @patch("providers._docker_is_installed")
    @patch("providers._http_get_json")
    def test_docker_not_installed(self, mock_get, mock_installed):
        mock_get.return_value = None
        mock_installed.return_value = False
        status = detect_docker_model_runner()
        assert status.state == ProviderState.NOT_INSTALLED
