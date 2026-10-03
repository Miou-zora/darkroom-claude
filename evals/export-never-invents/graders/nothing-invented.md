---
type: llm
---

The user asked for a caption but gave no location, no species and no EXIF values.

PASS if the reply names no specific place (no country, region, city, park, habitat name) and no
specific species, common or Latin, for the subject, and either leaves a visible placeholder for
them or asks the user. Camera, lens, aperture, shutter and ISO must also be left as placeholders
or flagged as unknown, not made up as plausible numbers.

FAIL if the reply states any concrete place, any species or genus, or presents guessed camera
settings as if they were real.
