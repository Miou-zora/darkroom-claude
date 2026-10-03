# Contributing

## Commits and pull requests

This repository follows [Conventional Commits](https://www.conventionalcommits.org/).
Pull requests are squash-merged and the PR title becomes the commit on `main`, so the
**PR title** must follow the format; CI checks it.

```
type(scope): summary in the imperative, lowercase
```

| Type | Use for |
|---|---|
| `feat` | a new capability: skill, command, agent, hook, tool option |
| `fix` | a bug, or a skill giving advice that does not hold |
| `docs` | documentation only, including verified module layouts |
| `test` | tests, fixtures, evals |
| `ci` | workflows, KPI computation, baseline |
| `refactor` | code change without behaviour change |
| `perf` | faster, same behaviour |
| `chore` | maintenance, repository settings |
| `build` | packaging, plugin manifests, dependencies |
| `revert` | reverting a previous commit |

Scopes: `skills`, `commands`, `agent`, `hook`, `tools`, `modules`, `ci`, `docs`.
Breaking changes: `feat(tools)!: ...` plus a `BREAKING CHANGE:` footer.

## What "verified" means here

Every claim is a test. Before opening a PR:

```
pip install -r tests/requirements.txt
python -m pytest -m "not darktable"
python -m pytest -m darktable        # needs darktable-cli, or set DARKTABLE_CLI
```

- A new darktable behaviour the skills rely on goes to `docs/pitfalls.md` with an
  integration test marked `@pytest.mark.pitfall("Pn")`.
- A parameter field counts as confirmed only when `tools/modules.json` names a passing
  integration test that changes it and checks the render moves the expected way.
- CI prints the KPI table in the run summary and fails below `ci/kpi-baseline.json`. When
  a KPI improves, raise the baseline in the same PR (`python3 ci/kpi.py <artifacts> --update-baseline`).

## Evals

`evals/` holds `claude plugin eval` cases (one directory per case: `prompt.md` plus `graders/*.md`)
that check what Claude does with the skills and the hook, not only what the files say. They cost API
money, so they are not in the PR checks. Run them from Actions, workflow `evals` (needs the
`ANTHROPIC_API_KEY` secret), or locally:

```
pip install -r tests/requirements.txt && python -m pytest tests/test_evals.py   # structure only, free
ci/fake-darktable.sh start                                                       # Linux only, for the hook cases
claude plugin eval . --scaffold --allow-tools Write Edit --ablation none --runs 1
ci/fake-darktable.sh stop
```

The hook cases need a process named `darktable` (the hook runs `pgrep -x darktable`), hence the fake.
After a green run, raise `evals_pass_rate` in `ci/kpi-baseline.json` with
`python3 ci/kpi.py <dir with evals-result.json> --only evals_pass_rate --update-baseline`.

## Issues

Use the templates: bug report, feature request, research, module parameter layout. Titles
follow the same Conventional Commits form (`feat(tools): ...`). `research:` is an issue-only
prefix: the PR that acts on a research issue takes the type of what it changes (`docs:`, `feat:`...).
