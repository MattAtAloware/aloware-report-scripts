# Security Policy

## Data Classification

Scripts in this repo process and render **client-confidential data**:

| Data type | Source | Handled by |
|---|---|---|
| Agent names | Aloware `users` table | `build_email.py` (rendered into HTML) |
| Company names | Aloware `companies` table | Embedded in report output |
| Time-in-status metrics | Aloware `agent_audits` table | Rendered into charts and tables |
| Recipient email addresses | Data contract `meta.recipients` | Passed through — never logged |

**Scripts in this repo never receive, store, or log raw email addresses or customer PII.** Data flows in via the data contract JSON and out via the rendered HTML file only.

## What Never Goes in This Repo

- Real client data (company names, agent names, email addresses)
- Database credentials or API keys
- Actual report output files (HTML, PDF, CSV)
- Baseline CSV files
- Any file containing a real `company_id` mapped to a real company name

The `.gitignore` enforces this for output files. Do not commit fixture files containing real client data.

## Test Fixtures

All test fixtures must use synthetic data:
- Company names: `"Test Corp"`, `"Acme Inc"`, etc.
- Agent names: `"Agent One"`, `"Test User"`, etc.
- Company IDs: `9999`, `0000`, etc.
- Email addresses: `test@example.com`, `agent@testcorp.com`

## Responsible Disclosure

This is an internal Aloware repository. If you discover a security issue:

1. Do **not** open a public GitHub issue
2. Contact the repository owner directly via internal Slack (`@matt`)
3. Include: description of the issue, potential impact, and reproduction steps

## Dependency Policy

All non-stdlib dependencies must be pinned to an exact version (e.g., `matplotlib==3.8.4`). Unpinned dependencies create supply chain risk. The CI pipeline will flag any unpinned installs.
