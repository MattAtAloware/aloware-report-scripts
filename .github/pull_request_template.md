## Summary

<!-- What does this PR change and why? -->

## Type of change

- [ ] Bug fix (renderer produces wrong output)
- [ ] New script or output format
- [ ] Refactor (no behavior change)
- [ ] Docs / tests only

## Gate checklist

**All boxes must be checked before this PR can be merged.**

- [ ] `python -m py_compile <script>` passes on every changed `.py` file
- [ ] Script exits `0` on valid fixture input and produces output ≥ 10 KB
- [ ] Script exits `1` with clear stderr on malformed/empty input
- [ ] Output starts with `<!DOCTYPE html>` (HTML scripts)
- [ ] All non-stdlib dependencies are pinned to exact versions
- [ ] No hardcoded email addresses, company names, or client IDs
- [ ] `CHANGELOG.md` updated with this change under the correct version
- [ ] Test fixtures use synthetic data only (no real client names or IDs)
