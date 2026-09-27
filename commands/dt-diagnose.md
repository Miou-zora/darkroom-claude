---
description: Measure one or more RAW photos with their darktable sidecars and name what to fix
argument-hint: <RAW file(s) or folder>
---

Diagnose the photos in: $ARGUMENTS

Use the `photo-diagnose` skill. For each RAW that has a `.xmp` sidecar:

1. Render it with `tools/render.py` into a scratch folder (never next to the originals) with
   `--phone`, and read the measurements.
2. Look at the render at full view, at phone size and on a 100% crop of the subject.
3. Report per photo: the numbers, the problem in one line, the proposed correction in pipeline
   order. Do not modify any sidecar: this command only diagnoses.
