# aloware-report-scripts

Python renderer scripts for Aloware Cowork report skills. Fetched at runtime by Claude — never bundled inside the skill directory.

## Overview

This repo contains the deterministic rendering layer of the **Claude-orchestrates, Python-renders** pattern. Claude gathers data from Metabase, writes a typed JSON data contract, then fetches and executes a script from this repo to produce the final output. Claude never generates report HTML, PDF, or CSV directly.

```
┌─────────────────────────────┐     ┌──────────────────────────────┐
│  Claude (orchestration)     │     │  This repo (rendering)       │
│                             │     │                              │
│  1. Fetch script via GitHub ├────▶│  agent-status-report/        │
│     MCP (pre-data-queries)  │     │    build_email.py            │
│  2. Query Metabase          │     │                              │
│  3. Write data contract JSON│     │  (future reports go here)    │
│  4. py_compile check        │     │                              │
│  5. Run script w/ timeout   │────▶│  --input contract.json       │
│  6. Verify output file      │     │  --out output.html           │
│  7. Deliver via subagent    │◀────│  exit 0 + valid HTML output  │
└─────────────────────────────┘     └──────────────────────────────┘
```

## Security & Reliability Guarantees

Every script in this repo is held to the following contract by the consuming skill:

| Gate | What the skill checks |
|---|---|
| **Fetch integrity** | Script must be ≥ 100 bytes after base64 decode |
| **Syntax check** | `python -m py_compile` before execution — corrupt fetches never run |
| **Timeout** | `timeout 120` wraps all executions — hangs are fatal errors |
| **Output existence** | Output file must exist after exit 0 |
| **Output size** | 10 KB minimum, 512 KB maximum — empty or bloated output is rejected |
| **Output validity** | Output must start with `DOCTYPE` or `<html` |
| **No improvisation** | If any gate fails, the skill aborts — Claude never generates fallback HTML |

## Scripts

### `agent-status-report/build_email.py`

Generates a fully static, email-safe HTML Agent Status Time Report with embedded base64 PNG charts (matplotlib/Pillow).

**Consuming skill:** `agent-status-time-report` 
**Dependencies:** `matplotlib==3.8.4`, `Pillow==10.3.0` (pinned) 
**Input:** `--input <path/to/report_data.json>` 
**Output:** `--out <path/to/output.html>` — self-contained HTML, 35–60 KB, safe for Gmail inline email bodies 
**Exit codes:** `0` = success, `1` = error (stderr has details)

**How Claude fetches and runs it:**
```python
import base64, subprocess

# Step 1 — fetch
result = mcp__github__get_file_contents(
    owner="MattAtAloware",
    repo="aloware-report-scripts",
    path="agent-status-report/build_email.py"
)
content = base64.b64decode(result["content"]).decode("utf-8")
open("/tmp/agent-status/build_email.py", "w").write(content)

# Step 2 — syntax check
subprocess.run(["python", "-m", "py_compile",
    "/tmp/agent-status/build_email.py"], check=True)

# Step 3 — run with timeout
subprocess.run([
    "timeout", "120",
    "python", "/tmp/agent-status/build_email.py",
    "--input", "/tmp/agent-status/report_data.json",
    "--out",   "/tmp/agent-status/output.html"
], check=True)
```

**Data contract:** See [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md) for the full schema.

### `agent-status-report/html_template.md`

Interactive HTML widget template with Chart.js. Used for in-chat display (not email delivery).

## Repository Structure

```
aloware-report-scripts/
├── README.md                        # This file
├── CHANGELOG.md                     # Version history (semver)
├── CONTRIBUTING.md                  # Development workflow
├── STATUS.md                        # Operational SHA/status tracker
├── agent-status-report/
│   ├── build_email.py               # Email renderer (matplotlib charts)
│   └── html_template.md             # Interactive widget template
└── docs/
    └── DATA_CONTRACT.md             # Data contract schema reference
```

## Adding a New Script

1. Create folder: `<skill-slug>/`
2. Implement `build_email.py` accepting `--input <contract.json>` and `--out <output.html>`
3. Exit `0` on success with a valid HTML file at `--out`; exit `1` with a stderr message on any error
4. Ensure output is ≥ 10 KB and starts with `<!DOCTYPE html>`
5. Use only stdlib + explicitly pinned packages (document in CONTRIBUTING.md)
6. Test with `python -m py_compile` before pushing
7. Update `CHANGELOG.md` and this README
8. Reference the new path in the skill's `SKILL.md`

## Related Repos

| Repo | Purpose |
|---|---|
| [`connection-rate-scripts`](https://github.com/MattAtAloware/connection-rate-scripts) | Connection Rate Report renderers |
| [`numberguard`](https://github.com/MattAtAloware/numberguard) | NumberGuard scan scripts |
