# Grabber

!!! warning "Breaking change: `grab` is ray-based"
    `grab` no longer takes a world-coordinate `point`. It always grabs a
    grabbable within `radius` metres of the **desktop cursor ray's hit
    point** — aim first with
    [`CursorClient.set_position`](cursor.md). A ray miss is reported as
    `GrabResult.grabbed == False` (not an error); VR mode fails with
    `FAILED_PRECONDITION`.

!!! example "Runnable example"
    [`python/examples/grabber_grab.py`](https://github.com/MLShukai/ResoniteIO/blob/main/python/examples/grabber_grab.py) — a full positive pick-up: spawn a Mirror from the inventory, hold the cursor on it, `grab` at the ray hit point, then `release`. The grabbed object stays at the cursor position where it was grabbed and follows the hand from there.

!!! tip "Operating the held / equipped item"
    After grabbing, drive the interactions an avatar can perform on the
    held object:

    - [`use`](#resoio.grabber.GrabberClient.use) presses a button
      (`primary` = left-click, `secondary` = right-click) and **holds it
      down** until [`unuse`](#resoio.grabber.GrabberClient.unuse). While
      grabbing, a primary press aligns the object; while a tool is
      equipped it activates the tool. The hold persists across RPCs, so a
      Pen can be pressed, dragged via
      [`CursorClient.set_position`](cursor.md), then released to draw a
      stroke. The optional `strength` (0..1, default `1.0`) is the analog
      pressure of the primary press — a `BrushTool`/Pen reads it as pen
      pressure — and is ignored for the secondary button.
    - [`click`](#resoio.grabber.GrabberClient.click) is a convenience for
      a single press+release (e.g. one-shot align).
    - [`equip`](#resoio.grabber.GrabberClient.equip) /
      [`dequip`](#resoio.grabber.GrabberClient.dequip) equip a grabbed
      tool into the hand / remove it. `equip` is a no-op when no `ITool`
      is grabbed.

    `GrabState.held_buttons`, `is_tool_equipped`, and
    `equipped_tool_name` report the resulting state.

::: resoio.grabber.GrabberClient

::: resoio.grabber.GrabResult

::: resoio.grabber.GrabState
