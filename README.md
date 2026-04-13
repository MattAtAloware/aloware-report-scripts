# Aloware Report Scripts

Pinned Python scripts for Aloware automated reports. Fetched at runtime by Cowork scheduled tasks.

## Scripts

### `agent-status-report/build_email.py`

Generates a fully static, email-safe HTML Agent Status Time Report with embedded JPEG chart images.

**Dependencies:** `matplotlib`, `Pillow`

**Usage:**
```bash
pip install matplotlib Pillow --break-system-packages -q

curl -sL https://raw.githubusercontent.com/MattAtAloware/aloware-report-scripts/main/agent-status-report/build_email.py -o /tmp/build_email.py

python /tmp/build_email.py \
  --rows '[{"agent_name":"Ana Cruz","status_code":"1","total_seconds":8435}]' \
  --company "Company Name" \
  --start-date 2026-04-06 \
  --end-date 2026-04-06 \
  --company-id 1234 \
  --out /tmp/report.html
```

**Output:** ~35 KB self-contained HTML file safe for Gmail inline email bodies.
