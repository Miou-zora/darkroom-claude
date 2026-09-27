---
name: photo-diagnose
description: >
  Measure a photo before touching any setting: tonal range, clipping, color cast in linear
  light, where the eye goes, sharpness at 100%. Then propose corrections in scene-referred
  pipeline order. Use when asked to develop, improve, fix, brighten or judge a photo, or to
  choose between two shots.
---

# Diagnose before editing

Nothing gets changed until the problem has a name and a number.

## Measure

Render the current state (`tools/render.py`), then read the JSON:

- **Tonal range**: luminance p1, p50, p99.5. A p99.5 around 0.5 means the brightest part
  is a mid grey: the image looks veiled. Blacks at p1 below 0.01 are already full.
- **Clipping**: `clipped_pct`. Above ~0.1% outside speculars, the highlights need care.
- **Color cast**: measure a neutral zone **in linear light**. Undo the sRGB curve first
  (`c <= 0.04045 ? c/12.92 : ((c+0.055)/1.055)^2.4`), then R/G and B/G. On gamma values a
  strong cast looks acceptable.
- **Where does the eye go**: it goes to the brightest, most contrasted, most saturated and
  sharpest area. If that is not the subject, something competes with it.
- **100% crops** on the subject: focus, noise, sharpening artifacts. Judge local contrast and
  denoise only there, never on the full view.

Look at the rendered image, not only the numbers. A text check never catches a render problem.

## Correct, in pipeline order

Scene-referred: correct upstream of tone mapping, never after it.

1. White balance, 2. exposure, 3. highlight reconstruction, 4. denoise, 5. crop and
perspective, 6. `sigmoid` (contrast and skew together: raising contrast alone blocks the
shadows of a dark subject), 7. `colorbalancergb`, 8. local contrast (local laplacian, check at
100%), 9. local masks to guide the eye (darken the competitor before brightening the subject,
+0.3 EV max).

Exposure is tuned by measurement, not by eye: sweep 3 values, keep the one that lifts p99.5
without clipping the subject and without turning a dark background grey.

## Report

For each image: the numbers, the problem named in one line, the proposed change, and the
render after the change with the same numbers. When two candidate shots compete, compare them
at the size they will be seen (see `frame-for-social`) and at 100%.
