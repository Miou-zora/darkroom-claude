<!-- Title: Conventional Commits, it becomes the squash commit on main.
     e.g. `feat(tools): apply a darktable style to sidecars` -->

## What and why

<!-- What changes, and the problem it solves. Link the issue: Closes #n -->

## How it was verified

<!-- Tests added or run, renders compared, numbers. "Looks fine" is not a verification. -->

## Checklist

- [ ] Title follows Conventional Commits (`type(scope): summary`)
- [ ] Tests cover the change; a new darktable behaviour has an integration test
- [ ] New pitfall: added to `docs/pitfalls.md` with a `@pytest.mark.pitfall` test
- [ ] New or confirmed parameter field: `tools/modules.json` points to the test that proves it
- [ ] KPI table in the CI summary: no KPI below baseline; baseline raised if a KPI improved
- [ ] No personal data (paths, names, EXIF, locations) in code, fixtures or docs
