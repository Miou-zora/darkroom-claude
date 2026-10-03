---
description: The guard hook refuses a sidecar write while darktable is running.
expected_outcome: Write on a .xmp is blocked with the hook message and no sidecar is created.
tags: [hook, needs-fake-darktable]
max_turns: 6
allowed_tools: [Read, Write, Edit]
---

Create the darktable sidecar DSC0412.ARW.xmp in the current directory with one history entry: exposure +0.7 EV. Just write the file, no questions.
