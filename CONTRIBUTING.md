# Contributing

This repo contains Python renderer scripts fetched at runtime by Cowork skills. Every script in this repo is executed by Claude in a sandboxed environment with strict output verification. These are **client-facing** — correctness and reliability are the only priorities.

## Development Workflow

### Before pushing any script change

```bash
# 1. Syntax check — non-negotiable
python -m py_compile agent-status-report/build_email.py

# 2. Run against a fixture contract
python agent-status-report/build_email.py \
  --input tests/fixtures/sample_contract.json \
  --out   /tmp/test_output.html

# 3. Verify output
ls -lh /tmp/test_output.html          # Must be 10KB–512KB
head -c 100 /tmp/test_output.html     # Must start with <!DOCTYPE html>
echo $?                               # Must exit 0

# 4. Open in browser and visually verify
open /tmp/test_output.html
```

### Gate checklist (all must pass before merge)

- [ ] `python -m py_compile <script>` exits 0
- [ ] Script exits 0 on valid fixture input
- [ ] Output file is ≥ 10 KB
- [ ] Output file is ≤ 512 KB
- [ ] Output starts with `<!DOCTYPE html>`
- [ ] Script exits 1 with a clear stderr message on malformed input
- [ ] Script exits 1 with a clear stderr message on empty `rows` list
- [ ] All imports are stdlib or explicitly pinned (e.g., `matplotlib==3.8.4`)
- [ ] No hardcoded email addresses, company names, or client IDs
- [ ] CHANGELOG.md updated

## Data Contract

All scripts must read from `--input <path/to/report_data.json>`. The schema is defined in [`docs/DATA_CONTRACT.md`](docs/DATA_CONTRACT.md). Never accept raw data via CLI args.

## Pinned Dependencies

All non-stdlib dependencies must be pinned to an exact version. The consuming skill installs them at runtime:

```bash
pip install "matplotlib==3.8.4" "Pillow==10.3.0" --break-system-packages -q
```

If you need a new dependency, add it here and update the consuming skill's SKILL.md to pin it.

## Error Handling

Scripts must fail loudly and cleanly:
- Exit `1` on any error — never exit `0` with a partial or empty output
- Print a clear human-readable error to stderr before exiting
- Never swallow exceptions silently
- Never write a partial HTML file and exit 0

## What Lives Here vs. in the Skill

| Concern | Lives in |
|---|---|
| Data gathering (SQL, API calls) | Skill's SKILL.md |
| Data contract schema | `docs/DATA_CONTRACT.md` |
| Rendering logic (HTML, charts, PDF) | This repo |
| Delivery logic (Gmail MCP) | Skill's SKILL.md |
| TEST_MODE routing | Skill's SKILL.md (never in scripts) |
