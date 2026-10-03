# darkroom-claude

A Claude Code plugin for measured RAW development in [darktable](https://www.darktable.org/).
Claude diagnoses your photos with numbers, edits the XMP sidecars safely, frames them so the
subject reads on a phone, and exports them for publishing. Works with stock darktable, no
patched build, no GUI automation.

## Install

```
/plugin marketplace add Miou-zora/darkroom-claude
/plugin install darkroom-claude@darkroom-claude
```

Requirements: darktable 5.x (tested on 5.6, macOS), Python 3 with `numpy` and `Pillow`.
`darktable-cli` is found in the macOS app bundle or on `PATH`; set `DARKTABLE_CLI` otherwise.

## What's inside

| Kind | Name | What it does |
|---|---|---|
| Skill | `photo-diagnose` | Measure before editing: tonal range, clipping, color cast in linear light, where the eye goes, 100% crops. Corrections in scene-referred pipeline order. |
| Skill | `darktable-xmp` | The rules for editing sidecars without silent failures, and for keeping `library.db` in sync. |
| Skill | `frame-for-social` | Aspect limits, phone-size check (390 px), subject share of the frame, resolution budget, carousel order. |
| Skill | `darktable-export` | Export through `darktable-cli`, sRGB, EXIF and GPS check, caption from real EXIF values. |
| Command | `/dt-diagnose` | Diagnose one or more photos, change nothing. |
| Command | `/dt-carousel` | Full pipeline for a social media carousel, with approval steps. |
| Agent | `darkroom-reviewer` | Independent visual review of renders at full view, phone size and 100%. |
| Hook | `guard_darktable_open` | Blocks writes to `.xmp` and `library.db` while darktable is running. |
| Tool | `tools/xmp.py` | Decode and append history entries, read and write module params by field name. |
| Tool | `tools/render.py` | Render through `darktable-cli` in isolation and measure. |
| Tool | `tools/subject.py` | Bounding box of the main subject on a render, to frame crops by measurement. |
| Tool | `tools/dbsync.py` | Align `library.db` on edited sidecars, dry run by default. |

## Why this exists

Editing a darktable sidecar by hand fails silently in many ways, all hit in real sessions:

- uppercase hex in `params`: the module is dropped, exit code 0;
- a second module instance without `iop_order_list`: ignored, `params ok` in the log;
- `darktable-cli` never overwrites its output: a tuning loop keeps measuring the old file;
- darktable trusts `library.db` over the sidecar and rewrites the sidecar on open and close.

The skills carry the method that catches these, and the tools make the safe path the easy one:
every change is rendered and measured, every write is backed up, dry-run first and verified
pixel by pixel afterwards.

## Writing to library.db

`tools/dbsync.py` writes to darktable's internal SQLite database, which is not a public API.
It refuses to run while darktable is open, backs the DB up, runs in one transaction, refuses
rows where DB and sidecar already disagree unless told otherwise, and ends with
`PRAGMA integrity_check`. The alternative is to reload each sidecar from the darktable GUI.
A Lua-based path through darktable itself is being evaluated in [#2](https://github.com/Miou-zora/darkroom-claude/issues/2).

## Related projects

- [w1ne/darktable-mcp](https://github.com/w1ne/darktable-mcp): MCP server, library and ratings
  through darktable's Lua API; module editing needs a patched darktable.
- [YaddyVirus/darktable-mcp](https://github.com/YaddyVirus/darktable-mcp): MCP server with simple
  adjustments stored in its own sidecar.
- [darkroom-xmp-tools](https://github.com/wmakeev/darkroom-xmp-tools): read and update module
  params in darktable XMP files.

darkroom-claude focuses on the method (measure, render, verify) rather than on exposing
darktable as a set of remote calls. It can be used alongside an MCP server.

## CI and KPIs

Every claim the skills make is a test. CI runs them on a real darktable 5.6.1 (AppImage) with
a CC0 Sony A7 III sample from [raw.pixls.us](https://raw.pixls.us/), then computes KPIs and
fails if one misses its threshold ([`ci/kpi-baseline.json`](ci/kpi-baseline.json), a ratchet:
thresholds only go up). The table is printed in each run's summary.

| KPI | Meaning | Threshold |
|---|---|---|
| `tests_pass_rate` | unit and integration tests passing | 100% |
| `darktable_tests_run` | integration tests actually executed, not skipped | baseline |
| `pitfalls_covered` | pitfalls of [`docs/pitfalls.md`](docs/pitfalls.md) reproduced by a passing test | baseline |
| `param_fields_confirmed` | fields of [`tools/modules.json`](tools/modules.json) proven by a passing render test | baseline |
| `always_on_tokens` | context the plugin adds to every session (`claude plugin details`) | at most 1000 |
| `manifests_valid` | `claude plugin validate` on both manifests | pass |

A KPI that could not be measured counts as failed. Run locally:

```
pip install -r tests/requirements.txt
python -m pytest -m "not darktable"      # unit tests, no darktable needed
python -m pytest -m darktable            # needs darktable-cli (or DARKTABLE_CLI)
```

## Status

Early. See the [issues](https://github.com/Miou-zora/darkroom-claude/issues) for the roadmap. Module parameter layouts known so far are in
[`docs/module-params.md`](docs/module-params.md); contributions of verified layouts are welcome.
See [`CONTRIBUTING.md`](CONTRIBUTING.md): Conventional Commits, squash merge, what "verified" means here.

## License

MIT
