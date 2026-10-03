# Known pitfalls

Every pitfall the skills warn about, each with the test that reproduces it on a real
darktable. CI reports how many are covered (`pitfall coverage` KPI) and fails if a covered
pitfall stops behaving as documented: that means darktable changed and the skills are wrong.

A pitfall is covered when a test carries `@pytest.mark.pitfall("Pn")` and passes.

| ID | Pitfall | Consequence if ignored |
|---|---|---|
| P1 | `darktable-cli` never overwrites its output, it writes `name_01.jpg` beside it | a tuning loop measures the old file and concludes a parameter has no effect |
| P2 | `params` written in uppercase hex | the module is dropped, the render is unchanged, exit code 0 |
| P3 | a second module instance (`multi_priority 1`) without `iop_order_list` | the instance is ignored, `params ok` in the log |
| P4 | `exposure` v7 field order: `int mode, float black, float exposure` | writing the EV in `black` crushes the image instead of brightening it |
| P5 | `crop` v3 edges are normalized to the module input | a crop computed on the wrong dimensions gives the wrong aspect ratio |
| P6 | a new entry with the same `(operation, multi_priority)` replaces the previous one | appending a second crop does not intersect crops, the last one wins |
| P7 | the same sidecar renders identically twice | without it, "pixel identical after write" proves nothing |
| P8 | `history_end` below the entry count (undo in darktable) | entries past `history_end` are inactive; appending after them is wrong |
| P9 | darktable trusts `library.db` over the sidecar and rewrites it on open and close | a hand-edited sidecar is silently lost |
| P10 | a drawn mask darktable cannot resolve (group id without a row, `mask_mode` 2, `blend_cst` 0, unknown `mask_version`) | no error: the module acts on the whole image, `params ok` in the log |
| P11 | uppercase hex in `mask_points` | `darktable-cli` segfaults and writes nothing (uppercase `params` only drops the module, P2) |

P9 needs a running darktable GUI and is covered by the guard hook tests only (the hook blocks
writes while darktable runs), not by a reproduction.
