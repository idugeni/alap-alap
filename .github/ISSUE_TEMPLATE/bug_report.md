---
name: Bug Report
about: Report reproducible incorrect behavior
title: '[BUG] '
labels: bug
assignees: ''
---

## Summary

Describe the incorrect behavior clearly and concisely.

## Minimal reproduction

Provide the smallest command or code sample that reproduces the problem:

```text
python main.py ...
```

Steps:

1.
2.
3.

## Expected behavior

What should have happened?

## Actual behavior

What happened instead? Include the exit code, HTTP status, or result fields when relevant.

## Environment

- Operating system:
- Python version (`python --version`):
- Alap-Alap version (`python main.py info` or installed package version):
- Entry point (`python main.py`, `alap-alap`, Python API, or REST API):
- Headless or visible mode:
- Proxy scheme, if used (do not include credentials):
- Config source (defaults, YAML, or environment overrides):

## Diagnostics

- [ ] `python main.py health` output included
- [ ] Relevant traceback or redacted log excerpt included
- [ ] The issue reproduces with a controlled test target
- [ ] Integration/browser details included when applicable

```text
Paste redacted diagnostics here.
```

## Security and privacy

Do not post CAPTCHA tokens, API keys, passwords, proxy credentials, private URLs, database contents, account information, or unredacted logs. Replace sensitive values with placeholders.

## Additional context

Add any other information that helps isolate the problem.
