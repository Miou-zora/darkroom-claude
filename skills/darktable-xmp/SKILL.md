---
name: darktable-xmp
description: >
  Rules and tools for editing darktable XMP sidecars and keeping library.db in sync:
  decode module params, append history entries (crop, exposure, style modules),
  handle multi-instance modules, verify every change by rendering. Use whenever a task
  reads or writes a darktable .xmp, darktable's library.db, or asks to apply darktable
  settings, a style or a crop to RAW files without the GUI.
---

# Editing darktable sidecars

Tools live in `tools/` at the plugin root (two levels above this skill's base directory):
`xmp.py` (read, append, `get_field`/`set_field`/`default_params` by field name for modules in `modules.json`), `render.py` (render and measure), `dbsync.py` (align library.db).

## Before writing anything

1. **Is darktable running?** `pgrep -x darktable`. If yes, stop and ask the user to quit it.
   Check again right before each write, not only at the start: users reopen it between steps.
   The plugin hook blocks obvious writes, but do not rely on it alone. What it sees: `cp`, `mv`,
   `tee`, `sed -i` or `>` aimed at a `.xmp`, SQL writes through `sqlite3` on `library.db`,
   `dbsync.py --write`, Write/Edit on a sidecar or the DB, and `python` (inline `-c`, heredoc, or a
   script file it can read) that names a `.xmp` or `library.db` and has a write signal (`open()` in
   `w`/`a`/`x`/`+` mode, `write_text`, `.write(`, `shutil.copy`/`move`, `os.replace`/`rename`,
   SQL `insert`/`update`/`delete`). What it does not see: a script that builds the path or the
   write at run time (`importlib`, `eval`, a path assembled from pieces), a script that runs
   another script, code reading its input from a pipe or a file the hook cannot open (other
   machine, relative path after a `cd`), and writes by another process. It also errs the other
   way: a script given a sidecar path that writes any other file is blocked too. The check is
   only a net; run `pgrep -x darktable` yourself.
2. **Back up** every sidecar you will touch (next to it, with a dated suffix) and `library.db`.
   No git on photo folders: a backup is the only undo.
3. **Read the history**: `python3 tools/xmp.py check FILE.xmp` then `show`. If `history_end`
   is lower than the entry count, the user undid steps in darktable: ask before appending.

## Writing

- Never edit existing entries. Append a new one: darktable keeps the last entry of each
  `(operation, multi_priority)` pair. A new `crop` with `multi_priority 0` replaces the old crop.
- `params` in **lowercase hex**. Uppercase decodes as garbage, darktable drops the module,
  export exit code stays 0.
- **Never guess a struct layout.** Copy a blob darktable wrote itself (another image, a preset in
  `data.db` table `presets`, a style in `style_items`) and change one field. Confirm which field
  moved by rendering two values: the effect must go the expected way.
- Known layouts (darktable 5.6): `crop` v3 = 4 floats left, top, right, bottom (normalized to the
  module input, after `flip` and `ashift`) + 2 ints ratio (the GUI aspect lock: pass
  `crop_params(..., aspect=(4, 5))` rather than leaving 0/0). `exposure` v7 = int mode, float
  black, float exposure, float, float, int, int. See `docs/module-params.md`.
- Blend params: copy the `blendop_params` of an existing entry (neutral = mask_mode 0), with
  `blendop_version="14"`. Parametric masks (mask_mode 3) depend on pixel values, not on
  position: they can be copied between images. Drawn masks cannot be written yet.
- **Second instance of a module** (`multi_priority 1`): the sidecar needs an explicit
  `darktable:iop_order_list` containing it, or the instance is ignored silently. Copy the list
  from an image where darktable created the instance itself, same `iop_order_version`
  (`xmp.with_iop_order_list`). `tools/iop_order_v4.txt` is a v4 list with `colorbalancergb,1`.
- Styles: take modules from `data.db` `style_items`, but leave out image-specific ones
  (`temperature`, `exposure`, `rawprepare`...) unless the user wants them copied.

## Verifying

- Render with `python3 tools/render.py RAW XMP OUT.jpg`. It deletes OUT first
  (darktable-cli never overwrites: it writes `OUT_01.jpg` and you would measure the old file),
  uses a throwaway config and an in-memory library, and reports `params_wrong`.
- `params ok` only means the blob decoded. To prove a module acts, render with and without it
  and diff the pixels. A zero diff means it was ignored.

## library.db

For an image already in the library, darktable trusts `library.db` over the sidecar and
rewrites the sidecar from the DB on open and close. An edited sidecar is lost unless:

- the user reloads it from the GUI (lighttable, "load sidecar file"), or
- `dbsync.py` aligns the DB, darktable closed: dry run first, read the report, then `--write`.
  Divergent rows (DB and sidecar already disagreeing before your edit) are refused unless
  `--accept-divergent`: show them to the user, they may be an older edit that never reached
  the DB.

`library.db` is not a public API. Prefer the GUI reload when there are few images.

After writing: dry run again (everything aligned), render from the real files and compare to
the validated renders pixel by pixel.
