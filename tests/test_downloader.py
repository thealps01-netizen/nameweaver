"""Tests for model downloaders — Ollama pull + HF GGUF download."""

import hashlib
import json
from unittest.mock import patch

import downloader


class _FakeResponse:
    """Mimic the context-manager HTTPResponse yielded by urlopen."""

    def __init__(self, lines: list[bytes] = None, body: bytes = b"", headers: dict = None):
        self._lines = lines or []
        self._body = body
        self._pos = 0
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)

    def read(self, size=-1):
        if size < 0:
            chunk = self._body[self._pos :]
            self._pos = len(self._body)
            return chunk
        chunk = self._body[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


class TestPullOllama:
    def test_pull_streams_progress(self):
        lines = [
            json.dumps({"status": "pulling", "completed": 50, "total": 100}).encode(),
            json.dumps({"status": "pulling", "completed": 100, "total": 100}).encode(),
            json.dumps({"status": "success"}).encode(),
        ]

        updates = []
        with patch("downloader.urllib.request.urlopen", return_value=_FakeResponse(lines=lines)):
            ok = downloader.pull_ollama(
                "llama3:8b",
                on_progress=lambda pct, msg: updates.append((pct, msg)),
            )

        assert ok is True
        # Progress events contain both pulling percentages and the success ping
        assert any(u[0] == 50 for u in updates)
        assert any(u[0] == 100 for u in updates)

    def test_pull_handles_error_event(self):
        lines = [
            json.dumps({"status": "pulling", "error": "model not found"}).encode(),
        ]
        with patch("downloader.urllib.request.urlopen", return_value=_FakeResponse(lines=lines)):
            ok = downloader.pull_ollama("nonexistent")
        assert ok is False

    def test_pull_handles_connection_error(self):
        with patch(
            "downloader.urllib.request.urlopen",
            side_effect=ConnectionError("refused"),
        ):
            ok = downloader.pull_ollama("llama3:8b")
        assert ok is False

    def test_pull_empty_name(self):
        assert downloader.pull_ollama("") is False

    def test_pull_respects_cancel(self):
        lines = [
            json.dumps({"status": "pulling", "completed": 10, "total": 100}).encode(),
            json.dumps({"status": "pulling", "completed": 20, "total": 100}).encode(),
        ]
        calls = {"n": 0}

        def cancel():
            calls["n"] += 1
            return calls["n"] > 1  # Cancel after first line

        with patch("downloader.urllib.request.urlopen", return_value=_FakeResponse(lines=lines)):
            ok = downloader.pull_ollama(
                "llama3:8b",
                should_cancel=cancel,
            )
        assert ok is False


class TestDownloadGguf:
    def test_download_writes_file(self, tmp_path):
        body = b"x" * 2048
        resp = _FakeResponse(body=body, headers={"Content-Length": str(len(body))})
        with patch("downloader.urllib.request.urlopen", return_value=resp):
            path = downloader.download_gguf(
                "org/repo",
                "model-q4.gguf",
                tmp_path,
            )
        assert path is not None
        assert path.exists()
        assert path.read_bytes() == body

    def test_download_invalid_repo(self, tmp_path):
        path = downloader.download_gguf("no-slash", "file.gguf", tmp_path)
        assert path is None

    def test_download_connection_error(self, tmp_path):
        with patch(
            "downloader.urllib.request.urlopen",
            side_effect=ConnectionError("refused"),
        ):
            path = downloader.download_gguf("org/repo", "f.gguf", tmp_path)
        assert path is None

    def test_download_sha_mismatch_deletes_file(self, tmp_path):
        body = b"abc"
        resp = _FakeResponse(body=body, headers={"Content-Length": "3"})
        with patch("downloader.urllib.request.urlopen", return_value=resp):
            path = downloader.download_gguf(
                "org/repo",
                "f.gguf",
                tmp_path,
                expected_sha256="00" * 32,  # Guaranteed mismatch
            )
        assert path is None
        # No .part file left over
        parts = list(tmp_path.glob("*.part"))
        assert parts == []

    def test_download_progress_callback(self, tmp_path):
        body = b"y" * (1024 * 1024)  # 1 MB
        resp = _FakeResponse(body=body, headers={"Content-Length": str(len(body))})
        updates = []

        with patch("downloader.urllib.request.urlopen", return_value=resp):
            path = downloader.download_gguf(
                "org/repo",
                "f.gguf",
                tmp_path,
                on_progress=lambda pct, msg: updates.append((pct, msg)),
            )
        assert path is not None
        assert any(100 == u[0] for u in updates)


class TestListGgufFiles:
    def test_list_returns_gguf_only_with_the_published_hash(self):
        data = [
            {
                "path": "model-q4.gguf",
                "size": 5_000_000_000,
                "lfs": {"oid": "ab" * 32, "size": 5_000_000_000, "pointerSize": 134},
            },
            {"path": "model-q8.gguf", "size": 8_000_000_000},
            {"path": "README.md", "size": 1024},
            {"path": "config.json", "size": 512},
        ]
        resp = _FakeResponse(body=json.dumps(data).encode())
        with patch("downloader.urllib.request.urlopen", return_value=resp):
            files = downloader.list_gguf_files("org/repo")
        assert len(files) == 2
        assert all(f["path"].endswith(".gguf") for f in files)
        # HuggingFace publishes a SHA256 for every LFS file; a file without one
        # must report "no hash" rather than an empty-but-verified value.
        assert files[0]["sha256"] == "ab" * 32
        assert files[1]["sha256"] == ""

    def test_list_invalid_repo(self):
        assert downloader.list_gguf_files("no-slash") == []

    def test_list_http_error(self):
        with patch(
            "downloader.urllib.request.urlopen",
            side_effect=ConnectionError("x"),
        ):
            assert downloader.list_gguf_files("org/repo") == []


class TestPublisherHash:
    """Downloads are checked against the hash HuggingFace publishes (§ security).

    The downloader always supported ``expected_sha256``; nobody ever passed one,
    so every GGUF landed unverified.
    """

    def test_the_hash_is_read_off_the_listing(self):
        files = [{"path": "a.gguf", "sha256": "cd" * 32}, {"path": "b.gguf", "sha256": ""}]

        assert downloader.sha256_for_file(files, "a.gguf") == "cd" * 32

    def test_an_unknown_file_has_no_hash(self):
        assert downloader.sha256_for_file([{"path": "a.gguf"}], "other.gguf") == ""

    def test_a_matching_hash_says_so(self, tmp_path):
        body = b"weights"
        digest = hashlib.sha256(body).hexdigest()
        resp = _FakeResponse(body=body, headers={"Content-Length": str(len(body))})
        messages = []

        with patch("downloader.urllib.request.urlopen", return_value=resp):
            path = downloader.download_gguf(
                "org/repo",
                "f.gguf",
                tmp_path,
                expected_sha256=digest,
                on_progress=lambda _p, m: messages.append(m),
            )

        assert path is not None
        assert any("SHA256 verified" in m for m in messages)

    def test_no_published_hash_is_reported_as_unverified(self, tmp_path):
        body = b"weights"
        resp = _FakeResponse(body=body, headers={"Content-Length": str(len(body))})
        messages = []

        with patch("downloader.urllib.request.urlopen", return_value=resp):
            path = downloader.download_gguf(
                "org/repo", "f.gguf", tmp_path, on_progress=lambda _p, m: messages.append(m)
            )

        assert path is not None
        assert any("not verified" in m for m in messages)
        assert not any("SHA256 verified" in m for m in messages)
