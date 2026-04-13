# Aloware Report Scripts

Pinned Python renderer scripts for Aloware Cowork skills. Fetched at runtime by Claude — never bundled inside the skill directory.

## Pattern

All scripts follow the **Claude-orchestrates, Python-renders** convention documented in
[`MattAtAloware/cowork-skill-template`](https://github.com/MattAtAloware/cowork-skill-template).

**Claude writes a data contract JSON → this script reads it → output is produced.**
Claude never generates HTML/CSV/PDF directly.

Each script accepts:
- `--input` path to `report_data.json` (conforms to `cowork-skill-template/data_contract.schema.json`)
- `--out` path for the output file

See `cowork-skill-template/boilerplate/build_report.py` for the base template all scripts extend.

---

## Scripts

### `agent-status-report/build_email.py`

Generates a fully static, email-safe HTML Agent Status Time Report with embedded PNG chart images (matplotlib).

**Skill:** `agent-status-time-report`
**Dependencies:** `matplotlib`, `Pillow`

**How Claude fetches it:**
```python
result = mcp__github__get_file_contents(
    owner="MattAtAloware",
    repo="aloware-report-scripts",
    path="agent-status-report/build_email.py"
)
content = base64.b64decode(result["content"]).decode("utf-8")
open("/tmp/agent-status/build_email.py", "w").write(content)
```

**Invocation (after migration to data contract pattern):**
```bash
pip install matplotlib Pillow --break-system-packages -q
python /tmp/agent-status/build_email.py \
  --input /tmp/agent-status/report_data.json \
  --out   /tmp/agent-status/output.html
```

**Output:** ~35–60 KB self-contained HTML safe for Gmail inline email bodies.

> **Note:** The current script still accepts `--rows` as a raw JSON CLI argument (pre-data-contract).
> Migration to `--input report_data.json` is tracked in Phase 2 of the skill framework rollout.

---

## Adding a new script

1. Create a folder: `<skill-slug>/`
2. Copy `cowork-skill-template/boilerplate/build_report.py` as your starting point
3. Implement `render_email()` (and optionally `render_widget()`, `render_csv()`, `render_pdf()`)
4. Ensure `--input` reads from a data contract JSON conforming to `data_contract.schema.json`
5. Update this README
6. Reference the new script in the skill's `SKILL.md`
