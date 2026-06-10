# Manipulation

!!! warning "Breaking change: `grab` is ray-based"
    `grab` no longer takes a world-coordinate `point`. It always grabs a
    grabbable within `radius` metres of the **desktop cursor ray's hit
    point** — aim first with
    [`CursorClient.set_position`](cursor.md). A ray miss is reported as
    `GrabResult.grabbed == False` (not an error); VR mode fails with
    `FAILED_PRECONDITION`.

!!! example "Runnable example"
    [`python/examples/manipulation_grab.py`](https://github.com/MLShukai/ResoniteIO/blob/main/python/examples/manipulation_grab.py) — a full positive pick-up: spawn a Mirror from the inventory, hold the cursor on it, `grab` at the ray hit point, then `release`. The grabbed object is tweened into the hand and held in front of the chest.

::: resoio.manipulation.ManipulationClient

::: resoio.manipulation.GrabResult

::: resoio.manipulation.GrabState
