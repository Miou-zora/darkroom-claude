---
description: Reads are never blocked by the guard hook, even while darktable is running.
expected_outcome: Claude reads the sidecar and lists its modules, and the hook message never appears.
tags: [hook, needs-fake-darktable]
max_turns: 6
allowed_tools: [Read, Glob, Grep]
---

Read DSC0412.ARW.xmp in the current directory and list the modules in its history, in order.
