---
description: Prepare a set of darktable photos as a social media carousel, from diagnosis to export
argument-hint: <folder> <photo names in order>
---

Prepare a carousel from: $ARGUMENTS

Work in this order and stop for the user's approval at each marked step.

1. **Diagnose** every photo (`photo-diagnose` skill). Flag the ones never developed.
2. **Develop** the undeveloped ones, if the user agrees: ask which of their darktable styles to
   start from, and tune exposure by measurement (`darktable-xmp` skill). All edits go to
   sidecar copies in a scratch folder first. *Show a contact sheet, wait for approval.*
3. **Frame** for a phone screen (`frame-for-social` skill): ask whether the platform allows mixed
   aspect ratios, check the subject share at 390 px. *Show before and after, wait for approval.*
4. **Write**: darktable closed, backups made, sidecars copied, `library.db` aligned with
   `tools/reload.py` (`tools/dbsync.py` dry run and `--write` only as fallback), renders from
   the real files compared pixel by pixel to the approved ones.
5. **Export** (`darktable-export` skill) into a new folder, ordered names, EXIF and GPS checked,
   caption drafted from EXIF with placeholders for anything unknown.
