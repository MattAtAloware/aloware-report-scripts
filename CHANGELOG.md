# Changelog

All notable changes to this project will be documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) — [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [1.3.0] — 2026-04-13

### Changed
- **Skill hardening (render/deliver layer)** — consuming skill (`agent-status-time-report`) updated to enforce:
  - `python -m py_compile` syntax check on fetched script before any execution
  - `timeout 120` on all renderer invocations — hangs are fatal errors
  - Output file must exist, be 10 KB–512 KB, and start with `DOCTYPE` or `<html`
  - Data contract validated field-by-field before renderer is invoked
  - Human confirmation gate before any live send
  - Delivery subagent must return `SUCCESS: draft_id={id}` — missing draft ID = failure
  - Dependency versions pinned: `matplotlib==3.8.4`, `Pillow==10.3.0`
- **Working directory** hardened to `/tmp/agent-status/` with `rm -rf` + `mkdir` guarantee
- **TEST_MODE** — confirmed lives exclusively in `meta.test_mode` of data contract; never hardcoded in subagent prompt

### Added
- `CHANGELOG.md` — this file
- `CONTRIBUTING.md` — development workflow and gate checklist
- `docs/DATA_CONTRACT.md` — authoritative data contract schema reference
- README overhauled with architecture diagram, security gate table, and up-to-date usage

### Fixed
- Removed stale README note referencing `--rows` CLI flag (pre-data-contract pattern, no longer used)

---

## [1.2.0] — 2026-04-13

### Fixed
- `build_email.py`: `import matplotlib.pyplot as as plt` syntax error → `import matplotlib.pyplot as plt`
- `build_email.py`: `ax.tick_params(labelsizes=9)` invalid kwarg → `labelsize=9`

---

## [1.1.0] — 2026-04-13

### Added
- `STATUS.md` — operational SHA/last-commit tracker for Claude to use when pushing updates
- `agent-status-report/html_template.md` — interactive Chart.js widget template

### Changed
- `build_email.py` migrated to `--input <json_file>` data contract pattern (away from `--rows` CLI arg)

---

## [1.0.0] — 2026-04-13

### Added
- Initial repo
- `agent-status-report/build_email.py` — email-safe HTML renderer with matplotlib stacked bar and donut charts
