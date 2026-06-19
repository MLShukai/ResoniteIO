from __future__ import annotations

from pathlib import Path

import pytest

mark_e2e = pytest.mark.e2e

__all__ = ["mark_e2e", "save_camera_shot"]


async def save_camera_shot(out_path: Path) -> bool:
    """Capture one in-engine Camera frame and save it as an opaque RGB PNG.

    Pulls a single frame via :meth:`resoio.CameraClient.shot` (the same
    in-engine source as the ``resoio screenshot`` CLI) and writes it to
    ``out_path`` with the alpha channel dropped — the engine framebuffer's
    alpha is not 255 everywhere and would render washed-out if kept (mirrors
    ``cli/screenshot._encode_png``).

    These shots are reference-only, human-viewable artifacts, so a transient
    Camera failure must never fail an unrelated modality test: any exception
    is swallowed with a warning and ``False`` is returned. Returns ``True``
    when the file was written.
    """
    import numpy as np
    from PIL import Image

    from resoio import CameraClient

    try:
        async with CameraClient() as cam:
            frame = await cam.shot()
        rgb = np.ascontiguousarray(frame.pixels[..., :3])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgb, mode="RGB").save(out_path)
    except Exception as e:  # noqa: BLE001 - artifact capture must not fail the test
        print(f"camera shot {out_path.name!r} failed (ignored): {e!r}")
        return False
    return True
