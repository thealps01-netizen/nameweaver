# AGENTS.md — Nameweaver agent guide

Instructions for AI coding agents (Grok Build, Cline, OpenCode, etc.) working
on this repository. Read this before making changes.

## Project

Nameweaver is a **PyQt6 desktop app** that scores local LLM models against the
user's hardware (RAM/CPU/GPU) and helps download/run them via Ollama, LM Studio,
llama.cpp and Docker Model Runner.

- Language: Python 3.10+
- UI: PyQt6 (+ qtawesome icons)
- Entry point: `app.py` (`main()`)
- Tests: `pytest` in `tests/`
- Packaging: PyInstaller (`Nameweaver.spec`) + Inno Setup (`nameweaver.iss`)
- CI/CD: GitHub Actions — `test.yml` on PRs, `release.yml` on `v*` tags
- Single source of version: `version.py`
- Logs (runtime): `%LOCALAPPDATA%\Nameweaver\logs\nameweaver.log`

## Commands

```bash
pip install -r requirements-dev.txt      # install deps
pytest tests/ -q                         # run the test suite (must stay green)
QT_QPA_PLATFORM=offscreen python -c ...  # headless widget smoke tests
```

## Hard rules

1. **Never push directly to `main`.** Open a pull request.
2. **Tests must pass** (`pytest tests/ -q`) before a PR is ready.
3. **Do not claim visual/UX correctness.** A text agent cannot see the rendered
   window. Flag anything needing a human (or screenshot/vision) review.
4. **Real hardware & engines can't be tested in the cloud** (GPU detection,
   Ollama/LM Studio model detection, real `ollama pull`/run). These need a
   self-hosted runner on the user's machine or manual verification.
5. Keep changes minimal and match the surrounding code style.

## Security checklist (review every change touching these)

- `subprocess` calls MUST hide the console window on Windows (use the `_run`
  wrapper / `CREATE_NO_WINDOW`) and must avoid shell injection.
- Downloads MUST stay inside the target models directory (no path traversal).
- The auto-updater (`updater.py`) downloads and runs an installer — verify the
  source/asset and never weaken that path.
- Publisher trust / allowlist logic (`models.py`) is a safety feature; changes
  need justification.

## Agent roles

Run these as separate agents/subagents. Each has one job.

### 1. Developer
Implement a bug fix or feature: locate code → smallest correct change →
add/update pytest tests → `pytest tests/ -q` green → offscreen smoke test for UI
logic → open a PR with a clear description and updated `CHANGELOG.md`.

### 2. Reviewer (security-first)
Review the PR diff. Order: correctness bugs → security (see checklist above) →
simplification. Report findings as `file:line` ranked by severity. Approve only
if tests pass and no high-severity issues remain.

### 3. Test / QA
Maintain and grow the suite: logic tests for scoring, model classification,
provider detection, name-matching; offscreen construction + signal smoke tests
for widgets. Produce a human checklist for anything visual.

### 4. Release
Bump `version.py` (+ `__version_tuple__`), update `CHANGELOG.md`, commit, tag
`vX.Y.Z`, push the tag, watch the GitHub Actions `Release` workflow to success,
verify the installer + `.sha256` assets, report the release URL. Never release
if tests fail.

### 5. Triage
Turn a free-form user bug report into a structured GitHub issue: title,
environment (OS, app version), repro steps, expected vs actual, log path,
suspected area, priority label.

### 6. Visual reviewer (vision-capable models only)
Given a screenshot of the app, check layout, alignment, contrast, conflicting
info and overflow; list issues with locations. Final UX call stays with a human.

## Release process (reference)

```bash
# after a change is merged to main and ready to ship
# 1) edit version.py -> new X.Y.Z, and CHANGELOG.md
git commit -am "Release vX.Y.Z: ..."
git tag vX.Y.Z && git push origin main vX.Y.Z
# 2) GitHub Actions builds installer + creates the Release automatically
```
