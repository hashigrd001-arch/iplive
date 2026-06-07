"""FFmpeg subprocess wrapper.

Builds the FFmpeg command line based on the active StreamConfig +
DeviceProfile, then runs it as a child process. H.264 is written to stdout
and consumed by `tcp_server.py`, which forwards bytes to the connected
phone client.

We deliberately keep FFmpeg as the sole encoder — wrapping libx264 in
Python would be insane, and FFmpeg is already shipped with most distros
and the Android Platform Tools install bundle.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import DeviceProfile, StreamConfig

log = logging.getLogger(__name__)


@dataclass
class StreamerStats:
    pid: int | None = None
    running: bool = False
    last_error: str = ""


class FFmpegStreamer:
    """Runs FFmpeg, exposing stdout as a byte stream of H.264 NAL units."""

    def __init__(self, cfg: StreamConfig) -> None:
        self.cfg = cfg
        self.process: subprocess.Popen | None = None
        self.stats = StreamerStats()

    # ── command builder ────────────────────────────────────────

    def build_cmd(
        self,
        playlist_file: Path,
        profile: DeviceProfile,
    ) -> list[str]:
        ffmpeg = self.cfg.ffmpeg_path
        if shutil.which(ffmpeg) is None:
            log.warning("ffmpeg not found on PATH — set ffmpeg_path in config.json")

        # video filter chain
        #
        # Quality parity with hook_mode (v1.8.27): Lanczos resampling +
        # full-precision chroma and explicit BT.709 matrix/range. The
        # old ``flags=bicubic`` (no color tags) reproduced the
        # "ผิวเหลืองซีด" skin-tone shift on ColorOS/MIUI here exactly
        # like the pre-v1.8.19 hook path, because un-tagged 1080p gets
        # decoded as BT.601 on those OEMs. ``force_original_aspect_ratio
        # =decrease`` keeps the source aspect (no stretch) and the pad
        # centres it.
        vf: list[str] = []
        if profile.rotation_filter and profile.rotation_filter != "none":
            vf.append(profile.rotation_filter)
        vf.append(
            f"scale={self.cfg.width}:{self.cfg.height}:"
            "force_original_aspect_ratio=decrease:"
            "flags=lanczos+full_chroma_int+full_chroma_inp:"
            "in_color_matrix=auto:out_color_matrix=bt709:"
            "in_range=auto:out_range=tv"
        )
        vf.append(f"fps={self.cfg.fps}")
        # Pad/letterbox to keep aspect ratio safely.
        vf.append(
            f"pad={self.cfg.width}:{self.cfg.height}:"
            f"(ow-iw)/2:(oh-ih)/2:color=black"
        )
        vf.append("setsar=1")

        keyint = max(1, int(self.cfg.fps * self.cfg.keyint_seconds))

        cmd: list[str] = [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "warning",
            "-nostdin",
            # Input — concat demuxer with optional infinite loop.
            "-re",
        ]
        if self.cfg.loop_playlist:
            cmd += ["-stream_loop", "-1"]
        cmd += [
            "-f", "concat",
            "-safe", "0",
            "-i", str(playlist_file),
            # Drop audio entirely; only video goes over the wire.
            "-an",
            "-vf", ",".join(vf),
            # H.264 encode tuned for low-latency streaming.
            #
            # v1.8.27: baseline -> high profile. ``-tune zerolatency``
            # already forces bframes=0, so High here only adds CABAC
            # (better entropy coding, sharper at the same bitrate)
            # without re-introducing decode latency. Level bumped to
            # 4.2 to comfortably cover 1080p; every min-SDK-33 decoder
            # supports it. BT.709 tags added end-to-end (container +
            # H.264 VUI) so the phone never guesses BT.601.
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-profile:v", "high",
            "-level", "4.2",
            "-pix_fmt", "yuv420p",
            "-r", str(self.cfg.fps),
            "-g", str(keyint),
            "-keyint_min", str(keyint),
            "-sc_threshold", "0",
            "-b:v", self.cfg.video_bitrate,
            "-maxrate", self.cfg.video_maxrate,
            "-bufsize", self.cfg.video_bufsize,
            # Color metadata so MediaCodec decodes in BT.709 limited
            # range (matches the scaler's out_color_matrix above).
            "-color_range", "tv",
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-x264-params",
            "colormatrix=bt709:colorprim=bt709:transfer=bt709",
            # Output: Annex-B H.264 to stdout.
            "-f", "h264",
            "pipe:1",
        ]
        return cmd

    # ── lifecycle ──────────────────────────────────────────────

    def start(self, playlist_file: Path, profile: DeviceProfile) -> subprocess.Popen:
        if self.process and self.process.poll() is None:
            raise RuntimeError("FFmpeg is already running")
        cmd = self.build_cmd(playlist_file, profile)
        log.info("Starting ffmpeg: %s", " ".join(cmd))
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.stats = StreamerStats(pid=self.process.pid, running=True)
        return self.process

    def stop(self) -> None:
        p = self.process
        if not p:
            return
        if p.poll() is None:
            log.info("Terminating ffmpeg pid=%s", p.pid)
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                log.warning("ffmpeg did not exit, killing")
                p.kill()
                p.wait(timeout=2)
        self.stats.running = False
        # drain stderr to capture last error
        try:
            err = p.stderr.read().decode("utf-8", errors="replace") if p.stderr else ""
            if err.strip():
                self.stats.last_error = err.strip().splitlines()[-1]
                log.debug("ffmpeg stderr tail: %s", self.stats.last_error)
        except Exception:
            pass
        self.process = None

    def is_running(self) -> bool:
        return bool(self.process and self.process.poll() is None)
