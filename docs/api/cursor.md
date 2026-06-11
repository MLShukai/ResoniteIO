# Cursor

!!! warning "Breaking change: `set_position` now holds the cursor"
    `set_position` no longer performs a one-shot warp. It **holds** the
    in-engine cursor at the requested position until `release()` is called
    (`CursorState.held` reports the hold). The hold never grabs the OS mouse
    pointer, but while held, human mouse movement does not reach the
    in-engine cursor and clicks fire at the held position. Switching world
    focus deactivates the hold (`held` becomes `False`).

!!! example "Runnable example"
    [`python/examples/cursor_move.py`](https://github.com/MLShukai/ResoniteIO/blob/main/python/examples/cursor_move.py) — `get_position` → center → move → restore the desktop cursor.

::: resoio.cursor.CursorClient

::: resoio.cursor.CursorState
