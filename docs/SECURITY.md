# Nameweaver — Security Notes

## Summary

Nameweaver is a **read-only analysis tool** that connects only to local LLM
providers (Ollama, LM Studio, Docker Model Runner on `localhost`) and to the
HuggingFace Hub over HTTPS. No critical vulnerabilities were identified during
a source-level review. Below are **2 Medium**, **4 Low**, and **4 Info** notes
worth tracking. All findings are documented (no code changes required for the
current threat model).

## Threat Model

| Actor | Trust |
|-------|-------|
| Local user | Trusted (runs on own machine) |
| Network path | TLS to HuggingFace; plain HTTP to `127.0.0.1` only |
| Model files | Data artifacts (GGUF), not code — executed by an isolated daemon |
| Adversary | A concurrent local process with access to `%LOCALAPPDATA%` or loopback |

Nameweaver does **not** run as a service, does **not** open any listening
sockets, and does **not** execute downloaded content.

---

## Findings

### SEC-01 — Plaintext HuggingFace token in JSON config
- **Severity:** Medium
- **Location:** `cfg.py:58` (`hf_token: str = ""`)
- **Description:** When the user pastes an HF token into Settings, it is
  serialized to `%LOCALAPPDATA%\Nameweaver\config.json` as plaintext. Any
  process running as the same user can read it.
- **Impact:** Token theft → read access to the user's private HF repos and
  rate-limit bypass attributed to the user.
- **Recommendation:** Store secrets via Windows DPAPI (`CryptProtectData`) or
  the cross-platform `keyring` package. Fall back to env var `HF_TOKEN`.
- **Status:** Documented / Accepted risk (single-user desktop)

### SEC-02 — GGUF download integrity check is optional
- **Severity:** Medium
- **Location:** `downloader.py:125` (`expected_sha256: str | None = None`)
- **Description:** `download_gguf()` verifies SHA-256 only when the caller
  passes one. The current UI path (`app.py::_start_gguf_download`) does not
  compute or forward an expected hash.
- **Impact:** A MITM on HF CDN (very unlikely under TLS) or a compromised
  mirror could serve a tampered GGUF. Weights are data, not code, but a
  malicious GGUF could still crash the runtime or trigger parser bugs in
  llama.cpp / Ollama.
- **Recommendation:** Pull `lfs.oid` from `GET /api/models/{id}/tree/main`
  before download and pass it as `expected_sha256`. Abort on mismatch.
- **Status:** Planned fix

### SEC-03 — Exception messages may leak request URLs
- **Severity:** Low
- **Location:** `hf_api.py` (generic `except Exception` paths); `app.py`
  error dialogs
- **Description:** The `Authorization` header itself is **not** logged
  (verified: no `print`, `logger.debug`, or `repr(headers)` paths include
  it). However, `HTTPError` exceptions include the request URL, and if the
  URL ever carried a query-string credential it would surface in dialogs.
- **Impact:** Information disclosure in crash dialogs / log files.
- **Recommendation:** Add a `_redact(msg)` helper that strips `token=`,
  `Bearer `, and `api_key=` before displaying. Tokens are currently only
  sent in headers, so risk is latent, not active.
- **Status:** Accepted risk

### SEC-04 — User prompt is forwarded to localhost inference daemon
- **Severity:** Low (Info-bordering)
- **Location:** `runner.py::run_model` → `_run_openai_compatible`
- **Description:** `ChatDialog` forwards the user's prompt as JSON to
  `http://localhost:11434`, `:1234`, or `:12434`. This is the intended
  behavior — inference requires the text.
- **Impact:** Another local process could `netstat` and infer that inference
  is in progress; it cannot read the prompt body without racing the daemon.
- **Recommendation:** Document in README that localhost providers are
  assumed trusted. No code change.
- **Status:** Documented

### SEC-05 — `subprocess` calls for hardware detection
- **Severity:** Low (Info)
- **Location:** `hw.py:293,306,319,364,429,444,493,544,603,646`
- **Description:** 10 `subprocess.run` call sites invoke `nvidia-smi`,
  `powershell.exe`, and `wmic`. All pass **list-form** arguments with
  `shell=False` (default). No user-controlled string is ever interpolated
  into the argv.
- **Impact:** None. Command injection is not reachable.
- **Recommendation:** None. Keep `shell=False`, keep argv as a list.
- **Status:** Documented / Safe

### SEC-06 — HTML escaping in ChatDialog
- **Severity:** Info
- **Location:** `widgets/chat_dialog.py:118,157,166`
- **Description:** `_escape()` converts `&`, `<`, `>` before the prompt or
  streamed tokens are appended to the `QTextEdit`. This prevents rendered
  HTML/script-like fragments from the model output.
- **Impact:** None — correctly defended.
- **Recommendation:** Consider also escaping `"` and `'` if the output is
  ever inlined into an attribute context (not currently).
- **Status:** Documented / Safe

### SEC-07 — Model data is interpolated into HTML in DetailPanel
- **Severity:** Info
- **Location:** `widgets/detail_panel.py` (HTML string builder)
- **Description:** Fields like `model.name`, `model.license`, `model.notes`
  are concatenated into an HTML template rendered by `QTextBrowser`. The
  data sources are `data/models.json` (version-controlled) and HF API
  responses (which Nameweaver authors trust).
- **Impact:** If a malicious HF repo name contained `<script>`, QTextBrowser
  would **not** execute JavaScript (Qt's rich-text renderer is not a web
  engine), but layout could be broken with tags.
- **Recommendation:** Long-term, escape model fields the same way
  ChatDialog does, or switch `setTextFormat(Qt.TextFormat.PlainText)` for
  user-facing strings.
- **Status:** Accepted risk

### SEC-08 — Corrupt config backups may accumulate with tokens
- **Severity:** Low
- **Location:** `cfg.py` (`.corrupt_<timestamp>` rename path)
- **Description:** When `config.json` fails to parse, it is renamed to
  `config.json.corrupt_<ts>` and a fresh default config is written. The
  corrupt backup may still contain the user's previous `hf_token`.
- **Impact:** Secret lingers on disk in unobvious backup files; user cannot
  easily locate / shred.
- **Recommendation:** Either scrub `hf_token` from the backup before
  rename, or surface a dialog offering to delete the backup. Combine with
  SEC-01 (keyring).
- **Status:** Planned fix

### SEC-09 — Conservative network defaults
- **Severity:** Info
- **Location:** `providers.py` (800 ms probe timeout; `ssl.create_default_context()`)
- **Description:** All HTTP/HTTPS calls use the system CA bundle via the
  default SSL context. Provider health-checks time out at 800 ms so a
  dead daemon cannot stall the UI.
- **Impact:** None — secure defaults.
- **Recommendation:** Keep the timeouts documented.
- **Status:** Documented / Safe

### SEC-10 — `sys.excepthook` writes tracebacks to the log file
- **Severity:** Info
- **Location:** `app.py` crash handler
- **Description:** Unhandled exceptions are written to
  `%LOCALAPPDATA%\Nameweaver\crash.log` with full traceback. Tracebacks
  can include local variable values in some Python versions; paths and
  function arguments are always present.
- **Impact:** If a variable at the crash site held a token, it would be
  persisted to disk.
- **Recommendation:** Pair with SEC-03 (redaction helper) applied to the
  final formatted traceback before writing.
- **Status:** Documented

### SEC-11 — Install-command runner used `shell=True` on a parameter
- **Severity:** High (fixed)
- **Location:** `provider_control.py::run_install_command`
- **Description:** The function previously invoked `subprocess.run(command,
  shell=True, …)`. The only production caller forwards the output of
  `suggested_install_command(...)` without edits, but the exported function
  accepted any string — if the UI ever made the command editable, arbitrary
  shell injection would be reachable.
- **Impact:** Latent shell injection surface.
- **Recommendation (applied):** Reject any command that does not exactly
  match one produced by `suggested_install_command()`. Run matched commands
  with `shlex.split` + `shell=False`; `shell=True` is retained only for the
  Linux `curl | sh` Ollama installer, which is the sole whitelisted pipe.
- **Status:** Fixed

### SEC-12 — Unsanitized HF filename into download path
- **Severity:** High (fixed)
- **Location:** `downloader.py::download_gguf`
- **Description:** `filename` is sourced from the HF `/tree/main` API response
  and was joined directly with `dest_dir`. A malicious repo returning
  `"../../evil.exe"` (or a Windows path with drive letter / backslashes) would
  have caused the atomic rename to land outside the user-selected directory.
  The earlier non-finding entry incorrectly attributed filename provenance to
  `QFileDialog`; only `dest_dir` comes from the dialog.
- **Impact:** Path traversal on download destination.
- **Recommendation (applied):** Reject filenames containing path separators,
  drive letters, or parent references; resolve the destination and verify it
  is contained inside the resolved `dest_dir` before writing.
- **Status:** Fixed

---

## Best Practices Observed

- **Atomic config writes:** `tempfile.NamedTemporaryFile` + `os.replace`
  guarantees no partial config on power loss.
- **Minimal `shell=True`:** Hardware-detection subprocesses all use list-form
  argv. The install-command runner accepts only whitelisted commands, and
  enables `shell=True` solely for the Linux `curl | sh` Ollama installer.
- **Default SSL context:** No `ssl._create_unverified_context()`, no
  `verify=False`, no custom CA pinning.
- **User-chosen download paths:** Destination dirs come from `QFileDialog`.
  Nameweaver never writes outside the user-selected directory.
- **Network timeouts everywhere:** Every `urlopen` / POST call sets an
  explicit `timeout=`.
- **No dynamic code:** Grep confirms zero uses of `pickle`, `eval`, `exec`,
  `compile()`, `__import__()` with user input.
- **HF JSON is read-only:** Nameweaver only issues `GET` requests to HF.
  It never uploads or mutates remote state.
- **Cancellation discipline:** Long-running workers poll
  `should_cancel: Callable[[], bool]` so the user can always abort.

## Non-Findings (Checked, Safe)

| Class | Status | Why it does not apply |
|-------|--------|----------------------|
| Command injection | ✅ Not reachable | `shell=False` + hardware argv; install runner now whitelists commands (see SEC-11) |
| Path traversal | ✅ Not reachable | `dest_dir` from `QFileDialog`; HF-sourced filename sanitized + containment-checked (see SEC-12) |
| Arbitrary code execution | ✅ Not reachable | GGUF = data; Ollama isolates runtime |
| XML / YAML deserialization | ✅ N/A | Not used |
| SQL injection | ✅ N/A | No SQL, no database |
| Pickle deserialization | ✅ N/A | No pickle |
| SSRF | ✅ Not reachable | URLs are constants or `f"{HF_BASE}/…"` with `quote()`'d ids |
| Open redirect | ✅ N/A | No redirects honored |
| TOCTOU on config | ⚠️ Mitigated | `os.replace` is atomic on Windows NTFS |

## Recommendations (Future Work)

Prioritized backlog the user may adopt when convenient:

1. **(Medium)** Move `hf_token` to `keyring` or DPAPI. (SEC-01, SEC-08)
2. **(Medium)** Require SHA-256 verification on GGUF downloads. (SEC-02)
3. **(Low)** Add a `_redact()` helper and apply to crash-log tracebacks
   and error dialogs. (SEC-03, SEC-10)
4. **(Low)** Plain-text rendering mode for `DetailPanel`. (SEC-07)

## References

- OWASP Desktop App Security Top 10 — <https://owasp.org/www-project-desktop-app-security-top-10/>
- Python `ssl` module — <https://docs.python.org/3/library/ssl.html>
- HuggingFace Hub API — <https://huggingface.co/docs/hub/api>
- Windows DPAPI — <https://learn.microsoft.com/en-us/windows/win32/api/dpapi/>
- `keyring` package — <https://pypi.org/project/keyring/>

---

*Review date: 2026-04-16. Scope: source-level review only — not a
penetration test or dynamic analysis. Independent audit recommended
before any production / enterprise deployment.*
