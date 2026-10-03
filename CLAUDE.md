# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Claude Code **plugin** (skills, commands, an agent, a hook, and Python tools) for measured RAW
photo development in darktable. It edits `.xmp` sidecars and `library.db` directly, without a
patched darktable and without GUI automation, and it renders through `darktable-cli` to verify
every change pixel by pixel. There is no application runtime to "start"; the deliverable is the
plugin itself plus the tools it drives from `tools/`.

## Commands

```bash
pip install -r tests/requirements.txt

python -m pytest -m "not darktable"      # unit tests: xmp.py, dbsync.py, the guard hook — no darktable needed
python -m pytest -m darktable            # integration: needs darktable-cli (or DARKTABLE_CLI) + sample RAW
python -m pytest tests/test_xmp.py::test_append_increments_history_end -v   # single test

python3 ci/kpi.py artifacts              # recompute KPIs from pytest-*.json + plugin-details.txt + validate.txt
claude plugin validate .                 # validate the plugin manifest
claude --plugin-dir . plugin details darkroom-claude   # always-on token cost
```

`darktable-cli` is resolved from `$DARKTABLE_CLI`, the macOS app bundle, or `PATH` (see
`tools/render.py:CANDIDATES`). Darktable-marked tests download a CC0 Sony A7 III sample RAW from
raw.pixls.us on first run (cached via `$DARKROOM_SAMPLE` in CI) and skip if it's unavailable.

## Architecture

**Tools (`tools/`) do the real work; skills (`skills/*/SKILL.md`) carry the method as prose for
Claude to follow.** A skill never reimplements what a tool does — it tells Claude which tool to
call, in what order, and what pitfall to check for.

- `tools/xmp.py`: read darktable history from an XMP sidecar (`entries`, `history_end`) and
  append new entries (`append`). Never edits existing entries — darktable keeps the *last* entry
  per `(operation, multi_priority)` pair, so a change is always a new append.
- `tools/render.py`: renders a RAW+XMP pair through `darktable-cli` in an isolated config dir
  with an in-memory library (never touches the user's real `library.db`), then measures the
  output (luminance percentiles, clipped %). Parses `-d params` output to catch modules whose
  params blob failed to decode (`params_wrong`).
- `tools/dbsync.py`: the only thing here that writes to `library.db` (not a public API). Dry run
  by default; `--write` backs the DB up, runs one transaction, and ends with
  `PRAGMA integrity_check`. Refuses to run while darktable is open, refuses divergent rows unless
  `--accept-divergent`, refuses to delete history rows unless `--allow-delete`.
- `hooks/guard_darktable_open.py`: a `PreToolUse` hook (wired in `.claude-plugin/plugin.json`)
  that blocks `Write`/`Edit`/`Bash` writes to `.xmp` files or `library.db` while darktable is
  running, because darktable rewrites sidecars from the DB on open/close and would silently
  clobber a hand-edited sidecar.

**Why the sidecar model is fragile** (this is the reason the tools and skills exist, see
`docs/pitfalls.md` for the full list with P-numbers referenced by tests):

- `params` must be lowercase hex; uppercase decodes as garbage and the module is silently
  dropped with exit code 0.
- A second instance of a module (`multi_priority 1`) is ignored unless the sidecar carries an
  explicit `iop_order_list` naming it.
- `darktable-cli` never overwrites its output file — it writes `NAME_01.jpg` beside it, so a
  render loop that doesn't delete the old output first ends up measuring stale data.
- For an image already in the library, darktable trusts `library.db` over the sidecar and
  rewrites the sidecar from the DB on open/close — hence `dbsync.py` and the guard hook.
- Module parameter layouts (`docs/module-params.md`, `tools/modules.json`) are never guessed:
  a field only counts as "confirmed" once a passing integration test changed it and observed the
  render move as expected. Layouts without a test are copied from a blob darktable itself wrote
  (another sidecar, a preset/style row in `data.db`), never hand-derived from the source.

**Skills** (`skills/*/SKILL.md`, loaded by name/description, not always-on):
`photo-diagnose` (measure before editing, correct in scene-referred pipeline order),
`darktable-xmp` (the sidecar-editing rules above, as procedure), `frame-for-social` (phone-size
and aspect-ratio framing), `darktable-export` (export via `render.py`, EXIF/GPS check, caption
from real EXIF). **Commands** (`commands/*.md`) `/dt-diagnose` and `/dt-carousel` chain these
skills into read-only or approval-gated workflows. The **agent** `darkroom-reviewer` does
read-only visual QA on renders (full view, 390px phone size, 100% crop) and never touches
sidecars.

## CI and KPIs (`ci/kpi.py`, `.github/workflows/ci.yml`)

Every claim a skill makes is meant to be a passing test, tagged `@pytest.mark.pitfall("Pn")`
against `docs/pitfalls.md`, or referenced by `test` in `tools/modules.json` for a param field.
`tests/conftest.py` records every test outcome (with its pitfall markers) to
`$KPI_DIR/pytest-<suite>.json`; `ci/kpi.py` aggregates those plus `plugin-details.txt` (always-on
token cost) and `validate.txt` (manifest validation) into KPIs checked against
`ci/kpi-baseline.json` — a **ratchet**: thresholds only go up (`--update-baseline` raises them,
never lowers). A KPI that can't be measured counts as failed. When adding a test that covers a
pitfall or confirms a param field, add the marker / wire `tools/modules.json`'s `test` field, or
the KPI table won't reflect it.

## Working with real photo folders (no git there)

There's no version control on the user's photo library, so:
- back up every sidecar (dated suffix) and `library.db` before writing;
- check `pgrep -x darktable` right before every write, not just once — the guard hook covers
  obvious cases but isn't the only line of defense;
- after any sidecar edit, re-render and diff pixels against the previously validated render —
  `params ok` in the log only means the blob decoded, not that the module did anything.
