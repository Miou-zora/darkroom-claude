# Module parameter layouts

Layouts seen on darktable 5.6, all little-endian. A field marked confirmed was checked by
changing it and seeing the render move the expected way. Anything not listed here
must be copied from a blob darktable wrote, never guessed.

| Module | Version | Size | Layout |
|---|---|---|---|
| `crop` | 3 | 24 B | `float left, top, right, bottom` (0 to 1, relative to the module input, after `flip` and `ashift`), `int ratio_n, ratio_d` |
| `exposure` | 7 | 28 B | `int mode` (0 manual), `float black`, `float exposure` (EV), `float deflicker_percentile`, `float deflicker_target`, `int compensate_camera_exposure`, `int` (mode, black, exposure confirmed; the rest named from darktable source, untested) |
| `sigmoid` | 3 | 56 B | `float contrast`, `float skew`, `float display_white`, `float display_black`, ... (contrast and skew confirmed; the rest named from default values only) |
| `temperature` | 4 | 20 B | decoded as `float red, green, blue, float`, `int preset`; read only, never written |

Sizes only (copied as whole blobs, fields not individually confirmed): `colorbalancergb` v5
132 B, `denoiseprofile` v12 416 B, `diffuse` v2 60 B, `channelmixerrgb` v3 160 B.

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
