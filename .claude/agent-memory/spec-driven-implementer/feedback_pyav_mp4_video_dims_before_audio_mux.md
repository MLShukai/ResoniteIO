---
name: pyav-mp4-video-dims-before-audio-mux
description: PyAV mp4 muxer freezes stream params on first packet — video stream's width/height MUST be set before any audio packet is muxed, otherwise avcodec_send_frame fails with AVERROR_EXTERNAL on the first video frame.
metadata:
  type: feedback
---

In a muxed mp4 with both video (H.264) and audio (AAC) streams, PyAV / FFmpeg's mp4 muxer freezes stream metadata on the **first packet muxed into the container**. If the audio pump races ahead and writes the first AAC packet while the video stream still has `width=0`/`height=0` (because the first camera frame has not arrived yet), the video stream's metadata is finalised as 0×0 and the subsequent `v_stream.encode(first_real_frame)` call raises `av.error.ExternalError: [Errno 542398533] Generic error in an external library: 'avcodec_send_frame()'` — which is FFmpeg's `AVERROR_EXTERNAL`.

**Why:** mp4 needs all stream metadata up-front to write the moov atom. Other containers (matroska) tolerate late dim assignment, but mp4 does not.

**How to apply:** In any PyAV pipeline that adds both a video and an audio stream and only learns the video dimensions from the first frame, gate the audio mux behind an `asyncio.Event` (or equivalent) that the video pump sets after assigning `v_stream.width` / `v_stream.height` and **before** the first `_mux_video_packets` call. See \[\[record-muxed-pipeline\]\] (`python/src/resoio/cli/record.py::_record_muxed`) for the canonical implementation pattern.

Also note: the same constraint means a muxed-mp4 recording with a camera that never produces a frame will not be playable (audio is blocked) and PyAV `container.close()` may produce a zero-byte file. That is acceptable degenerate behaviour but worth documenting if a future contributor reports "muxed mode produces nothing".
