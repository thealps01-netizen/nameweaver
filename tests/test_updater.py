"""Tests for the update checker's decision logic.

Only the decision paths and the small pure helpers: whether a release is
offered, skipped, or reported as a failed check. The download-and-verify
pipeline is covered in test_ui_smoke.py. Nothing here touches the network.
"""

from unittest.mock import patch

import updater
from updater import _find_installer_asset, _is_newer, _parse
from version import __version__


def _newer_tag() -> str:
    """A tag strictly newer than the running version, so a bump cannot break these."""
    major, minor, patch = (int(part) for part in __version__.split("."))
    return f"v{major}.{minor}.{patch + 1}"


class TestVersionParsing:
    def test_strips_the_v_prefix(self):
        assert _parse("v1.2.3") == (1, 2, 3)

    def test_missing_components_are_allowed(self):
        assert _parse("2.0") == (2, 0)

    def test_a_tag_without_digits_parses_to_nothing(self):
        assert _parse("latest") == ()

    def test_newer_patch_is_newer(self):
        assert _is_newer("v0.1.30", "0.1.29") is True

    def test_same_version_is_not_newer(self):
        assert _is_newer("v0.1.29", "0.1.29") is False

    def test_older_version_is_not_newer(self):
        assert _is_newer("v0.1.28", "0.1.29") is False

    def test_shorter_but_higher_version_is_newer(self):
        assert _is_newer("v0.2", "0.1.29") is True


class TestInstallerAsset:
    def test_picks_the_exe(self):
        release = {
            "assets": [
                {"name": "notes.txt", "browser_download_url": "u1"},
                {"name": "Nameweaver_Setup.exe", "browser_download_url": "u2"},
            ]
        }
        assert _find_installer_asset(release) == "u2"

    def test_the_checksum_sidecar_is_not_the_installer(self):
        release = {
            "assets": [
                {"name": "Nameweaver_Setup.exe.sha256", "browser_download_url": "u1"},
            ]
        }
        assert _find_installer_asset(release) is None

    def test_a_release_without_assets(self):
        assert _find_installer_asset({}) is None


class TestSkipStore:
    def test_round_trip(self, tmp_path, monkeypatch):
        store = tmp_path / "update_skip.json"
        monkeypatch.setattr(updater, "_skip_store_path", lambda: str(store))

        assert updater._get_skipped_version() == ""

        updater._set_skipped_version("v0.1.30")

        assert updater._get_skipped_version() == "v0.1.30"

    def test_a_corrupt_store_reads_as_empty(self, tmp_path, monkeypatch):
        store = tmp_path / "update_skip.json"
        store.write_text("{ this is not json", encoding="utf-8")
        monkeypatch.setattr(updater, "_skip_store_path", lambda: str(store))

        assert updater._get_skipped_version() == ""


class TestUpdateCheckerDecision:
    """The QThread exists to keep the UI responsive; the decision is in _run()."""

    def _checker(self, monkeypatch) -> updater.UpdateChecker:
        checker = updater.UpdateChecker("owner", "repo")
        # _run() is driven inline here, so the thread it would quit is stubbed.
        monkeypatch.setattr(checker._thread, "quit", lambda: None)
        return checker

    def _release(self, tag: str, url: str | None = "https://host/Nameweaver_Setup.exe"):
        assets = (
            [] if url is None else [{"name": "Nameweaver_Setup.exe", "browser_download_url": url}]
        )
        return {"tag_name": tag, "body": "release notes", "assets": assets}

    def test_a_newer_release_is_offered_with_its_installer(self, qtbot, monkeypatch):
        tag = _newer_tag()
        monkeypatch.setattr(updater, "_fetch_latest", lambda owner, repo: self._release(tag))
        monkeypatch.setattr(updater, "_get_skipped_version", lambda: "")
        checker = self._checker(monkeypatch)
        offered = []
        checker.update_available.connect(lambda *args: offered.append(args))

        checker._run()

        assert offered == [(tag, "https://host/Nameweaver_Setup.exe", "release notes")]

    def test_an_already_skipped_version_is_not_offered_again(self, qtbot, monkeypatch):
        tag = _newer_tag()
        monkeypatch.setattr(updater, "_fetch_latest", lambda owner, repo: self._release(tag))
        monkeypatch.setattr(updater, "_get_skipped_version", lambda: tag)
        checker = self._checker(monkeypatch)
        offered, no_update = [], []
        checker.update_available.connect(lambda *args: offered.append(args))
        checker.no_update.connect(lambda: no_update.append(True))

        checker._run()

        assert offered == []
        assert no_update == [True]

    def test_a_newer_release_without_an_exe_is_not_offered(self, qtbot, monkeypatch):
        monkeypatch.setattr(
            updater, "_fetch_latest", lambda owner, repo: self._release(_newer_tag(), url=None)
        )
        monkeypatch.setattr(updater, "_get_skipped_version", lambda: "")
        checker = self._checker(monkeypatch)
        offered, no_update = [], []
        checker.update_available.connect(lambda *args: offered.append(args))
        checker.no_update.connect(lambda: no_update.append(True))

        checker._run()

        assert offered == []
        assert no_update == [True]

    def test_the_running_version_is_not_offered(self, qtbot, monkeypatch):
        from version import __version__

        monkeypatch.setattr(
            updater, "_fetch_latest", lambda owner, repo: self._release(f"v{__version__}")
        )
        monkeypatch.setattr(updater, "_get_skipped_version", lambda: "")
        checker = self._checker(monkeypatch)
        offered, no_update = [], []
        checker.update_available.connect(lambda *args: offered.append(args))
        checker.no_update.connect(lambda: no_update.append(True))

        checker._run()

        assert offered == []
        assert no_update == [True]

    def test_a_failed_lookup_is_reported(self, qtbot, monkeypatch):
        monkeypatch.setattr(updater, "_fetch_latest", lambda owner, repo: None)
        monkeypatch.setattr(updater, "_get_skipped_version", lambda: "")
        checker = self._checker(monkeypatch)
        failed, offered = [], []
        checker.check_failed.connect(lambda: failed.append(True))
        checker.update_available.connect(lambda *args: offered.append(args))

        checker._run()

        assert failed == [True]
        assert offered == []


class TestFriendlyError:
    """Install time failures are translated before the user sees them."""

    def test_ssl_failure_is_explained(self):
        title, body = updater._friendly_error(
            "<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>"
        )
        assert title == "Secure Connection Failed"
        assert "date/time" in body

    def test_dns_failure_is_explained(self):
        title, body = updater._friendly_error("<urlopen error [Errno 11001] getaddrinfo failed>")
        assert title == "No Internet Connection"
        assert "internet connection" in body.lower()

    def test_an_unknown_error_still_gets_a_title(self):
        title, body = updater._friendly_error("something odd happened")
        assert title == "Download Failed"
        assert body


def test_is_newer_against_a_higher_running_version():
    assert _is_newer("v1.0.0", "0.9.9") is True
    assert _is_newer("v0.9.9", "1.0.0") is False


def test_fetch_latest_returns_none_when_the_network_is_down(monkeypatch):
    """A dead network must not raise out of the checker."""

    def _boom(*args, **kwargs):
        raise OSError("no network")

    with patch("updater.urllib.request.urlopen", side_effect=_boom):
        assert updater._fetch_latest("owner", "repo") is None
