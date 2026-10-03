# Module parameter layouts

Layouts seen on darktable 5.6, all little-endian. A field marked confirmed was checked by
changing it and seeing the render move the expected way. Fields marked mapped are named from
darktable's source and checked against the blobs of its built-in presets (same size, plausible
values at every offset, `tests/test_darktable.py::test_preset_*`); that pins a layout, it does not
prove what a field does. Anything not listed here must be copied from a blob darktable wrote,
never guessed.

| Module | Version | Size | Layout |
|---|---|---|---|
| `crop` | 3 | 24 B | `float left, top, right, bottom` (0 to 1, relative to the module input, after `flip` and `ashift`), `int ratio_n, ratio_d` (the aspect lock, see below) |
| `exposure` | 7 | 28 B | `int mode` (0 manual), `float black`, `float exposure` (EV), `float deflicker_percentile`, `float deflicker_target`, `int compensate_camera_exposure`, `int` (mode, black, exposure confirmed; the rest named from darktable source, untested) |
| `sigmoid` | 3 | 56 B | `float middle_grey_contrast, contrast_skewness, display_white_target, display_black_target`, `int color_processing`, `float hue_preservation, red_inset, red_rotation, green_inset, green_rotation, blue_inset, blue_rotation, purity`, `int base_primaries` (middle_grey_contrast and contrast_skewness confirmed by a render test, the rest cross-checked against darktable's built-in presets) |
| `colorbalancergb` | 5 | 132 B | 33 fields, 32 `float` then `int saturation_formula`: shadows/midtones/highlights/global `_Y,_C,_H`, weights and fulcrums, `chroma_*`, `saturation_*`, `hue_angle`, `brilliance_*`, `vibrance`, `contrast` (saturation_global, vibrance and contrast confirmed by a render test, the rest cross-checked against darktable's built-in presets; full order in `tools/modules.json`) |
| `toneequal` | 2 | 72 B | 15 `float`: nine EV bands `noise, ultra_deep_blacks, deep_blacks, blacks, shadows, midtones, highlights, whites, speculars`, then `blending, smoothing, feathering, quantization, contrast_boost, exposure_boost`; `int details, method, iterations` (midtones, highlights and whites confirmed by a render test; `shadows` sits below the 5th percentile of the CI sample and is not measurable on it) |
| `bilat` | 3 | 20 B | `int mode` (0 bilateral, 1 local laplacian), `float sigma_r, sigma_s, detail, midtone` (detail confirmed by a render test) |
| `colorequal` | 4 | 128 B | `float threshold, smoothing_hue, contrast, white_level, chroma_size, param_size`, `int use_filter`, then 8 `sat_*`, 8 `hue_*` (degrees), 8 `bright_*` over red, orange, yellow, green, cyan, blue, lavender, magenta, then `float hue_shift` (mapped, no field confirmed) |
| `channelmixerrgb` | 3 | 160 B | six arrays of 4 `float` (`red, green, blue, saturation, lightness, grey`, the 4th slot unused), six `int` normalize flags, `int illuminant, illum_fluo, illum_led, adaptation`, `float x, y, temperature, gamut`, `int clip, version` (mapped, no field confirmed; enum values unknown beyond what presets show) |
| `temperature` | 4 | 20 B | decoded as `float red, green, blue, float`, `int preset`; read only, never written |

Sizes only (copied as whole blobs, fields not individually confirmed): `denoiseprofile` v12
416 B, `diffuse` v2 60 B.

`tools/modules.json` is the machine-readable form of this table; `xmp.get_field`, `set_field` and
`default_params` read it and refuse a module or version it does not list.

## crop ratio_n and ratio_d

The aspect lock of the crop module, kept so the GUI still holds the aspect when the crop is
edited by hand. `ratio_d` is the long side, `ratio_n` the short side (4:5 is `n=4, d=5`; 3:2 is
`n=2, d=3`); `crop_params(..., aspect=(4, 5))` writes them. `ratio_d` is negative when the crop is
oriented the other way than the module input: a landscape 4:3 crop of a portrait image is
`n=3, d=-4`. `0/0` is freehand (what `crop_params` wrote before), `n=0` with `|d|=1` is "original
image".

What a render shows (darktable 5.6, `darktable-cli`, `test_crop_ratio_trims_to_the_ratio`): the
rectangle comes from the four edges only, but an export trims it to a multiple of the ratio, the
long side `d` with the long side of the crop, `n` with the short one (a 3628 x 2012 crop with 5:4
exports at 3625 x 2012). 1:1 trimmed nothing in a probe; a reduced side above 16 trims nothing according to the source (untested). The sign
changes nothing in an export: it is known from darktable's source (`src/iop/crop.c`, `_commit_box`,
`_aspect_apply`) and from sidecars darktable wrote (`3,-4` and `2,3` in #11), not from a render.
Never checked in the GUI, headless: that the lock then shows the expected preset.

## Blobs in XMP

- `darktable:params` and `darktable:blendop_params` are either lowercase hex, or `gz` + two
  digits (compression ratio) + base64 of a zlib stream.
- In `library.db` the same fields are raw bytes (`BLOB`). `blendop_params` v14 is 420 bytes raw.

## Blend params v14

Observed only: first `uint32` is `mask_mode` (0 = off, 3 = enabled + parametric mask), second
is `blend_cst` (4 seen on every entry). Other fields not mapped yet.

## Contributing a layout

Open an issue or a PR with: module, version, blob size, the field you changed, the two values
rendered and what the render did. See [#1](https://github.com/Miou-zora/darkroom-claude/issues/1).
