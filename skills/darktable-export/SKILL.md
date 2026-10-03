---
name: darktable-export
description: >
  Export RAW files through darktable-cli with their sidecars for publishing: size limits,
  sRGB, JPEG quality, ordered file names, EXIF and GPS check, caption from real EXIF values.
  Use when asked to export, publish, prepare files for Instagram, or write a post caption.
---

# Export for publishing

## Before exporting

- The sidecars must be final: `tools/reload.py` succeeded (or a `tools/dbsync.py` dry run reports everything aligned), and the
  last renders were validated by the user.
- Pick an output folder that does not exist yet, or delete only the files you will replace,
  by name. darktable-cli never overwrites: it writes `name_01.jpg` beside the old file.

## Export

```
python3 tools/render.py RAW XMP "OUT/01 NAME.jpg" --size 1080 --height 1350
```

1080 px wide, 1350 px tall at most (4:5). `render.py` passes `--upscale false` and an isolated
config, so the result matches the validated renders exactly. Prefix files with their position
in the post (`01`, `02`...). To reorder later, rename in two passes through temporary names
with `mv -n`, never overwriting.

## Check each file

- Size and aspect as expected.
- Embedded profile is sRGB.
- **No GPS in EXIF** unless the user wants the location public. Read it with Pillow:
  `Image.open(p).getexif().get_ifd(0x8825)`.
- Look at the exported files together, at phone size.

## Caption

Fill the user's template with values **read from EXIF** (`Model`, `LensModel`, `FNumber`,
`ExposureTime`, `ISOSpeedRatings`, `DateTimeOriginal`), never from the template's example.
When settings vary across the post, give ranges. Never invent a location, a species or a story:
leave a visible placeholder and ask.
