---
name: frame-for-social
description: >
  Crop photos for social media so the subject reads on a phone: platform aspect limits,
  phone-size simulation, subject share of the frame, resolution budget, carousel order.
  Use when preparing photos for Instagram or any feed, building a carousel, or when the
  user asks whether subjects are visible on mobile.
---

# Framing for a phone screen

Most viewers see the post on a phone, where a feed image is about **390 points wide**.
A subject that looks fine on a monitor can be unreadable there.

## Constraints to check first

- **Aspect limits**: Instagram feed accepts 1.91:1 (landscape) to 4:5 (portrait). A 2:3
  portrait gets cropped by the app: frame it at 4:5 yourself. Check the platform's current
  rules instead of assuming, in particular whether a carousel may mix aspect ratios: ask the
  user, do not assume a single ratio.
- **Resolution budget**: after cropping, keep at least the export width (1080 px) of real
  pixels. Never upscale.

## Method

1. Export or render every candidate, then `render.py --phone` (390 px wide).
2. Look at all of them together at that size. For each, estimate the subject's share of the
   frame width.
   - Under ~30%: unreadable, crop tighter.
   - 40 to 70%: comfortable, with context kept.
   - Camouflaged subjects (insects on bark, grass, gravel) need more than bright ones.
3. **Measure the subject position on a render of the current crop**, not by eye on a grid of the
   full frame. Visual estimates put the subject against an edge or cut a flower off.
4. Crop at the same aspect ratio. In `crop` coordinates, width = height x ratio x (H/W of the
   module input). Check the result renders at the expected size (off by one pixel is darktable
   rounding, harmless).
5. Re-check at phone size, then at 100% that nothing important is cut.

## Carousel

- The first image decides whether people swipe: strongest, most readable subject first.
- Do not open with a camouflaged subject.
- Keep a visual rhythm: alternate colors or subjects rather than grouping similar shots.
