## Summary

Describe the problem and the resulting behavior. Keep the pull request focused on one concern.

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor with no intended behavior change
- [ ] Documentation
- [ ] Security hardening
- [ ] Build, CI, or dependency maintenance
- [ ] Breaking change

## Compatibility and security

- Breaking behavior or migration steps:
- Security impact and safe default:
- Changes to CLI options, Python interfaces, REST requests/responses, or config:

Use `N/A` where a section does not apply. Do not include credentials, proxy passwords, API keys, CAPTCHA tokens, private URLs, or account data.

## Validation

List the exact commands and relevant results:

```text
ruff check src/ tests/ main.py
black --check src/ tests/ main.py
pyright src/
python -m pytest tests/
```

- [ ] Non-integration tests pass locally
- [ ] New or changed behavior has focused tests, or the reason tests are not applicable is documented
- [ ] `pytest -m integration` was run when real-browser behavior changed, or the reason it was not run is documented
- [ ] `git diff --check` passes

## Documentation and repository hygiene

- [ ] README/API/config examples match the implementation
- [ ] User-visible changes are recorded under `Unreleased` in `CHANGELOG.md`
- [ ] No generated output, caches, logs, local databases, exports, virtual environments, or tool state are included
- [ ] No secrets or full tokens appear in the diff
- [ ] I reviewed the complete diff and removed unrelated changes

## Additional context

Add logs, screenshots, benchmarks, or follow-up work only when useful. Redact sensitive values and include a reproducible command/environment for performance claims.
