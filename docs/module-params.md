# Module parameter layouts

Layouts seen on darktable 5.6, all little-endian. A field marked confirmed was checked by
changing it and seeing the render move the expected way. Anything not listed here
must be copied from a blob darktable wrote, never guessed.

| Module | Version | Size | Layout |
|---|---|---|---|
| `crop` | 3 | 24 B | `float left, top, right, bottom` (0 to 1, relative to the module input, after `flip` and `ashift`), `int ratio_n, ratio_d` |
| `exposure` | 7 | 28 B | `int mode` (0 manual), `float black`, `float exposure` (EV), `float deflicker_percentile`, `float deflicker_target`, `int compensate_camera_exposure`, `int` (mode, black, exposure confirmed; the rest named from darktable source, untested) |
| `sigmoid` | 3 | 56 B | `float middle_grey_contrast, contrast_skewness, display_white_target, display_black_target`, `int color_processing`, `float hue_preservation, red_inset, red_rotation, green_inset, green_rotation, blue_inset, blue_rotation, purity`, `int base_primaries` (middle_grey_contrast and contrast_skewness confirmed, the rest named from darktable source, untested) |
| `colorbalancergb` | 5 | 132 B | 33 fields, 32 `float` then `int saturation_formula`: shadows/midtones/highlights/global `_Y,_C,_H`, weights and fulcrums, `chroma_*`, `saturation_*`, `hue_angle`, `brilliance_*`, `vibrance`, `contrast` (saturation_global, vibrance and contrast confirmed, the rest named from darktable source, untested; full order in `tools/modules.json`) |
| `temperature` | 4 | 20 B | decoded as `float red, green, blue, float`, `int preset`; read only, never written |

Sizes only (copied as whole blobs, fields not individually confirmed): `denoiseprofile` v12
416 B, `diffuse` v2 60 B, `channelmixerrgb` v3 160 B.

`tools/modules.json` is the machine-readable form of this table; `xmp.get_field`, `set_field` and
`default_params` read it and refuse a module or version it does not list.

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
