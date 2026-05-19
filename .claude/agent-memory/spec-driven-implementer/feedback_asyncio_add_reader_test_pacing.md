---
name: asyncio-add-reader-test-pacing
description: asyncio.add_reader + os.pipe stdin tests must feed keystrokes paced across ticks, not as one atomic write.
metadata:
  type: feedback
---

End-to-end tests that drive a `loop.add_reader`-based CLI via `os.pipe()` stdin must **pace the keystroke writes with `asyncio.sleep`**, not dump the whole canned byte sequence with a single `os.write()` before the loop starts.

**Why:** add_reader fires as soon as data is available. If the entire sequence including an `exit` key (e.g. `q`) is buffered in the pipe before the producer coroutine first awaits, the reader drains it all atomically and sets the stop event in one callback. The drive loop then exits its `while not stop_event.is_set()` check before yielding *any* command, and the round-trip server records zero messages.

**How to apply:** wrap the keystroke feeder as a separate `asyncio.create_task(feed_keys())` coroutine that writes each byte chunk and `await asyncio.sleep(period * 2)` between writes. Start it after the run task is scheduled and cancel it in the `finally`. See `python/tests/resoio/cli/test_locomotion.py::test_drive_round_trip_via_cli` for the pattern. Real-world usage already paces keys at human speed so this only affects test harnesses.
