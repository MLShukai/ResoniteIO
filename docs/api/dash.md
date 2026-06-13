# Dash

!!! warning "Breaking change: rewritten around tabs + controls"
    The Dash modality was rewritten (wire-breaking). The old UI-tree dump
    (`get_tree` / `DashTree` / `DashElement` / `DashRect`) and the
    `list_screens` / `set_screen` / `DashScreen` surface are gone. The dash is
    now modelled as a **bottom tab bar** plus the **interactable controls** of
    the current tab: enumerate tabs with [`list_tabs`][resoio.dash.DashClient.list_tabs],
    switch with [`set_tab`][resoio.dash.DashClient.set_tab], enumerate the
    current tab's pressable / scrollable controls with
    [`list_controls`][resoio.dash.DashClient.list_controls], and act on one by
    `ref_id` with [`invoke`][resoio.dash.DashClient.invoke] /
    [`scroll`][resoio.dash.DashClient.scroll] /
    [`highlight`][resoio.dash.DashClient.highlight]. The `*_by_label` helpers
    add client-side label/index resolution while the wire stays `ref_id`-based.

!!! example "Runnable example"
    [`python/examples/dash_navigate.py`](https://github.com/MLShukai/ResoniteIO/blob/main/python/examples/dash_navigate.py) — opens the ESC dash → list tabs → set tab → list controls → invoke → close.

::: resoio.dash.DashClient

::: resoio.dash.DashState

::: resoio.dash.DashTab

::: resoio.dash.DashControl

::: resoio.dash.DashActionResult

::: resoio.dash.DashNoMatchError

::: resoio.dash.DashAmbiguousMatchError
