# Research: reload sidecars through darktable's Lua API instead of writing library.db

Issue: #2. Status: research done, decision below. Everything here was run on a copy of a
library (isolated config dir, never `~/.config/darktable`), darktable 5.6.0 on macOS, one
CC0 Sony A7 III RAW. What was not tested is listed at the end.

## Question

Can a Lua script running inside darktable reload the sidecars of a list of images through the
official API, so that `tools/dbsync.py` (which writes `library.db`, not a public API) is no
longer needed by default?

## Decision

**Yes. Lua `image:apply_sidecar` becomes the default reload path, `dbsync.py` stays as the
expert fallback** (darktable older than the Lua API 9.5.0, a build without Lua, or when you
want the dry-run report and the explicit refusals it gives).

Evidence: on four edit shapes (append, in-place edit, truncated history, second module
instance with `iop_order_list`), `apply_sidecar` left the same `history` rows, the same
`history_end` and the same `module_order` as `dbsync.py --write`, and a render from the
library was pixel identical (max diff 0) to a render from the sidecar. darktable does the
write, so there is no schema to track.

It does not remove the "darktable must be closed" constraint (see below), and the route
needs two workarounds (a dummy image to host the run, a config flag) that a tool has to carry.

## What exists (web search, before prototyping)

Found:

- `dt_lua_image_t:apply_sidecar(filename)` in the Lua API manual. Added by commit "lua/image.c -
  added apply_sidecar function to apply an XMP file to an image in lighttable" (wpferguson,
  committed by TurboGit, May 2025, Lua API 9.5.0). Per `src/lua/image.c` on master it calls
  `dt_history_load_and_apply(imgid, filename, 0)` and returns a boolean. The installed 5.6.0
  reports API 9.7.0.
- `dt_lua_image_t.sidecar` (read only path of the image's sidecar), `reset()`, `is_altered`,
  and `darktable.database.import()`. No function writes `library.db` rows directly.
- discuss.pixls.us, "REload sidecar files?" (2023): no Lua answer (it predates
  `apply_sidecar`); suggestions were the startup XMP check, re-import, `touch`, an in-memory
  library. A feature request for a manual refresh was still open in Aug 2023.
- w1ne/darktable-mcp (MIT): a Lua plugin with a file based JSON RPC bridge, plus `darktable-cli`
  for exports, and by design no `library.db` access. Its README says that for photos already in
  the library a manual "read sidecar files" step in lighttable is required.

Not found: any report of how `apply_sidecar` behaves (replace or merge, what it does to
`history_end`, `module_order`, the sidecar file), any use of it in darktable-mcp (code search
needs a sign-in, its source was not read, nor was issue #5), anything about calling it with the
GUI open.

## Prototype

`tools/reload_sidecars.lua` (first written under `experimental/lua-reload/`, promoted in #20): takes sidecar paths in the env var
`DARKROOM_SIDECARS` (one per line), finds each image by its `sidecar` property, calls
`apply_sidecar`, prints `RELOAD ok|FAILED|NOT_IN_LIBRARY path`.

`experimental/lua-reload/experiment.py` reproduces everything below:

```
python3 experimental/lua-reload/experiment.py /path/to/sample.ARW
```

The Lua run is hosted by a `darktable-cli` process (headless: `has_gui` is false) through
`--luacmd`, fed a second dummy image because `darktable-cli` always needs something to
export:

```
darktable-cli HOST.ARW out.jpg --width 8 --height 8 --core --configdir C --library C/library.db \
  --conf write_sidecar_files=never --conf lua/luarc/darktable_first_run_complete=TRUE \
  --luacmd 'dofile("reload_sidecars.lua")'
```

## Results

Setup per scenario: darktable imports `A.ARW` and writes its sidecar (11 history entries),
the sidecar is edited by hand, then each variant works on its own copy of the library. Renders
come from the library with the sidecar moved away, so only the DB can drive them.

| Scenario (sidecar edit) | lua rows / end | dbsync rows / end | lua vs dbsync | render vs sidecar reference |
|---|---|---|---|---|
| append: new exposure + crop | 13 / 13 | 13 / 13 | rows, end, module_order identical | lua 0, dbsync 0, untouched library 244 |
| inplace: existing exposure params changed | 11 / 11 | 11 / 11 | identical | lua 0, dbsync 0, untouched 114 |
| multi: second exposure instance + `iop_order_list` (P3) | 12 / 12 | 12 / 12 | identical | lua 0, dbsync 0, untouched 122 |
| shorter: last entry dropped | 10 / 10 | 10 / 10 | identical | lua 0, dbsync 0, untouched 78 |

Render columns are the max absolute pixel difference (0 to 255) against
`render.render(raw, sidecar)`. The untouched library column proves the DB render is able to
see a difference.

Differences between the two routes, the only ones observed:

- `history_hash`: darktable recomputes it (1 row after Lua), `dbsync.py` deletes it (0 rows,
  darktable recomputes later).
- `change_timestamp`: set by both.

Other findings:

- `apply_sidecar` replaces the image history with the sidecar's. It does not merge: the
  in-place and truncated cases end with exactly the sidecar's rows.
- It did not rewrite the sidecar, whatever `write_sidecar_files` was (`never`, `on import`,
  `after edit`): bytes identical before and after.
- Several images in one run work (two images reloaded, one call each). A path whose image is
  not in the library is reported by the script as `NOT_IN_LIBRARY` and nothing else happens.
- A second darktable process on the same library refuses to start (`database is locked`, "can't
  acquire database lock"). A Lua reload through `darktable-cli` therefore needs darktable
  closed, exactly like `dbsync.py`. This is the hook's job (`guard_darktable_open.py`) and the
  tool's own `pgrep` check, unchanged.
- **Lua is skipped on a fresh config.** darktable ignores `--luacmd` until its Lua first run is
  complete: with a new config dir, short runs silently print nothing and exit 0 (no `LUA ERROR`).
  `--conf lua/luarc/darktable_first_run_complete=TRUE` fixes it. A tool must check for its
  `RELOAD ...` lines, never assume success from the exit code. My first runs looked like they
  worked only because `darktable-cli` itself re-read the sidecar (next point).
- **`darktable-cli` re-reads the sidecar of any image it is given**, without Lua. Running
  `darktable-cli A.ARW out.jpg` on the library gave the same rows as the other two routes in all
  four scenarios (but `change_timestamp` stays unset). The mechanism was not traced in the source
  and it is not documented; it may depend on timestamps (not tested). Worth a follow-up, but
  `apply_sidecar` is the documented route, so it is the one the decision rests on.

## Not tested

- The GUI. The sandbox has no window server, so no Lua script ran inside an interactive
  darktable. Whether `apply_sidecar` called from the GUI refreshes what lighttable and darkroom
  show, and whether darktable then rewrites the sidecar on close (P9), is unknown. P9 stays
  documented as "not reproduced" in `docs/pitfalls.md`.
- Other darktable versions (only 5.6.0), other platforms, other RAW formats, duplicates
  (`NAME_01.EXT.xmp`; `image.sidecar` should give the right file but this was not run).
- Importing an image that is not in the library yet (`darktable.database.import`).
- Masks, drawn-mask history and `masks_history` (the table was empty in all runs).
- Large batches and timing (each host run is a few seconds, mostly RAW decode of the dummy).

## Follow-up #20: what was settled

- `tools/reload.py` and `tests/test_reload.py` implement the decision. On darktable 5.6.0 the four
  scenarios give the same rows, `history_end` and `module_order` as `dbsync.py --write`, and
  the render from the library is pixel identical to the render from the sidecar.
- Bare `darktable-cli RAW out` re-reads the sidecar whatever its mtime: with the sidecar set to
  now, to year 2000 and to year 2030, the edited history (12 rows) landed in the library each
  time, so it does not depend on timestamps. It stays a side effect of importing a path that is
  already in the library, not a documented reload, handles one image per run, and leaves
  `change_timestamp` unset. `reload.py` keeps the documented Lua route.
- `library.db.lock` holds the pid of the darktable process, NUL terminated; `reload.py` refuses on
  a live pid. A running GUI, duplicates, new imports, masks, other versions and platforms remain
  untested.

## Draft follow-up issue

Title: `feat(tools): reload sidecars through Lua apply_sidecar, keep dbsync as fallback`

> Context: research in #2 (`docs/research/lua-sidecar-reload.md`). On darktable 5.6.0,
> `image:apply_sidecar` run in a headless `darktable-cli` left the same history rows,
> `history_end` and `module_order` as `dbsync.py --write` on four edit shapes, with pixel
> identical renders, and darktable does the DB write.
>
> Scope:
> - `tools/reload.py SIDECAR...`: refuse if `darktable` runs or the library is locked, back up
>   `library.db` (dated suffix), run `reload_sidecars.lua` through `darktable-cli --luacmd` with
>   `--conf lua/luarc/darktable_first_run_complete=TRUE` and a dummy host image (`--host`, default
>   any other library image), isolated stdout parsing: fail unless every sidecar printed
>   `RELOAD ok`.
> - Verify afterwards with `dbsync.plan()` in dry run: `insert none, delete none, divergent
>   none` per sidecar, otherwise exit 1. This reuses the existing code as the check.
> - `dbsync.py` stays, documented as the fallback for darktable without Lua API 9.5.0 or without
>   Lua, and for its dry-run report.
> - Update the `darktable-xmp` skill: reload with `reload.py`, not `dbsync.py`, by default.
> - Tests marked `darktable`: the four scenarios of `experiment.py` as assertions (rows,
>   `history_end`, `module_order`, render diff 0), plus "no `RELOAD ok` line means failure".
>
> Open questions to settle first: does plain `darktable-cli RAW` reloading the sidecar depend on
> timestamps (it would make Lua unnecessary for the single image case)? Behaviour with the GUI
> open, if a Lua script can be shipped to lighttable. Duplicates (`_01`), new imports, masks.
>
> Acceptance: `python -m pytest -m darktable` green with the new tests, `claude plugin validate .`
> passes, KPI baseline ratchet updated.
