"""Tests for provider lifecycle helpers."""

import sys
from unittest.mock import MagicMock, patch

from provider_control import (
    START_ACTIONS,
    _wait_for_http_ready,
    open_installer_page,
    run_install_command,
    start_ollama_service,
    start_provider,
    suggested_install_command,
)


class TestWaitForHttpReady:
    @patch("provider_control._http_get_json")
    def test_returns_true_when_http_responds_immediately(self, mock_get):
        mock_get.return_value = {"ok": True}
        assert _wait_for_http_ready("http://x", timeout=1.0) is True

    @patch("provider_control._http_get_json")
    def test_returns_false_on_timeout(self, mock_get):
        mock_get.return_value = None
        assert _wait_for_http_ready("http://x", timeout=0.4) is False


class TestStartOllamaService:
    @patch("provider_control._http_get_json")
    def test_short_circuits_when_already_running(self, mock_get):
        mock_get.return_value = {"models": []}
        assert start_ollama_service() is True

    @patch("provider_control._ollama_is_installed")
    @patch("provider_control._http_get_json")
    def test_fails_when_not_installed(self, mock_get, mock_installed):
        mock_get.return_value = None
        mock_installed.return_value = False
        assert start_ollama_service() is False


class TestStartProviderDispatch:
    def test_unknown_action_returns_false(self):
        assert start_provider("bogus_action") is False

    def test_dispatch_table_covers_known_actions(self):
        assert "start_ollama" in START_ACTIONS
        assert "start_lmstudio" in START_ACTIONS
        assert "start_dmr" in START_ACTIONS


class TestSuggestedInstallCommand:
    def test_ollama_returns_command_or_url(self):
        cmd = suggested_install_command("ollama")
        assert cmd  # non-empty on all platforms

    def test_lmstudio_returns_something(self):
        assert suggested_install_command("lm studio")

    def test_unknown_provider_returns_empty(self):
        assert suggested_install_command("bogus") == ""

    def test_windows_uses_winget(self):
        if sys.platform == "win32":
            assert "winget" in suggested_install_command("ollama").lower()


class TestRunInstallCommand:
    def test_empty_command_fails(self):
        ok, out = run_install_command("")
        assert ok is False

    @patch("provider_control.webbrowser.open")
    def test_url_opens_browser(self, mock_open):
        ok, out = run_install_command("https://example.com")
        assert ok is True
        mock_open.assert_called_once_with("https://example.com")


class TestOpenInstallerPage:
    @patch("provider_control.webbrowser.open")
    def test_ollama_opens_url(self, mock_open):
        open_installer_page("Ollama")
        mock_open.assert_called_once()
        args, _ = mock_open.call_args
        assert "ollama.com" in args[0]

    @patch("provider_control.webbrowser.open")
    def test_unknown_provider_does_nothing(self, mock_open):
        open_installer_page("Bogus")
        mock_open.assert_not_called()
