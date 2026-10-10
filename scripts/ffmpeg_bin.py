"""ffmpeg / 媒体探测统一入口。

- 系统没有 ffmpeg，所以优先吃 ``imageio-ffmpeg`` 自带的静态二进制（含 libx264 / aac）。
- 它**不带 ffprobe**，所以探测一律走 PyAV（`av`），不要再找 ffprobe。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path

_FF_CACHE: str | None = None


@lru_cache(maxsize=1)
def ffmpeg() -> str:
    """返回可用的 ffmpeg 可执行文件路径。"""
    env = os.environ.get("AVE_FFMPEG")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "找不到 ffmpeg：装一个系统 ffmpeg，或设置 AVE_FFMPEG 指向二进制，"
            "或 `pip install imageio-ffmpeg`。"
        ) from exc


def run(args: list[str], *, capture: bool = True, check: bool = True,
        stdin=None, stdout=None) -> subprocess.CompletedProcess:
    """跑一条命令；开头的 "ffmpeg" 占位会被替换成真实二进制路径。"""
    args = list(args)
    if args and args[0] == "ffmpeg":
        args = args[1:]
    cmd = [ffmpeg(), *args]
    proc = subprocess.run(
        cmd,
        stdin=stdin,
        stdout=subprocess.PIPE if (capture and stdout is None) else stdout,
        stderr=subprocess.PIPE if capture else None,
        text=False,
    )
    if check and proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")[-2000:]
        raise RuntimeError(f"命令失败({proc.returncode})：{' '.join(cmd[:6])} …\n{err}")
    return proc


def ff(*args: str, capture: bool = True, check: bool = True, stdin=None, stdout=None):
    """以 ffmpeg 开头跑命令。"""
    return run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args],
               capture=capture, check=check, stdin=stdin, stdout=stdout)


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    rotation: int
    display_width: int
    display_height: int
    has_audio: bool
    audio_rate: int
    audio_channels: int
    video_codec: str
    audio_codec: str
    orientation: str          # portrait / landscape / square
    n_audio_streams: int

    def as_dict(self) -> dict:
        return asdict(self)


def _rotation_from_ffmpeg(path: Path) -> int:
    """从 ffmpeg -i 的 stderr 里抠旋转角（比 PyAV 的 side_data 稳）。"""
    try:
        proc = subprocess.run(
            [ffmpeg(), "-hide_banner", "-i", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        err = (proc.stderr or b"").decode("utf-8", "replace")
    except Exception:
        return 0
    m = re.search(r"displaymatrix:\s*rotation of (-?[\d.]+) degrees", err)
    if not m:
        m = re.search(r"rotate\s*:\s*(-?\d+)", err)
    if not m:
        return 0
    return int(round(float(m.group(1)))) % 360


def probe(path: str | Path) -> MediaInfo:
    """探测时长 / 画幅 / 帧率 / 旋转 / 音轨。"""
    import av

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"素材不存在：{path}")

    with av.open(str(path)) as container:
        vstream = next((s for s in container.streams if s.type == "video"), None)
        astreams = [s for s in container.streams if s.type == "audio"]
        if vstream is None:
            raise RuntimeError(f"没有视频轨：{path}")

        has_audio = bool(astreams)
        astream = astreams[0] if has_audio else None

        duration = 0.0
        if container.duration:
            duration = float(container.duration / av.time_base)
        if duration <= 0 and vstream.duration and vstream.time_base:
            duration = float(vstream.duration * vstream.time_base)
        if duration <= 0 and astream and astream.duration and astream.time_base:
            duration = float(astream.duration * astream.time_base)

        fps = float(vstream.average_rate) if vstream.average_rate else 30.0
        width = int(vstream.codec_context.width)
        height = int(vstream.codec_context.height)
        rotation = _rotation_from_ffmpeg(path)
        if rotation in (90, 270):
            disp_w, disp_h = height, width
        else:
            disp_w, disp_h = width, height

        orientation = "square"
        if disp_w < disp_h:
            orientation = "portrait"
        elif disp_w > disp_h:
            orientation = "landscape"

        return MediaInfo(
            path=str(path),
            duration=round(duration, 3),
            width=width,
            height=height,
            fps=round(fps, 4),
            rotation=rotation,
            display_width=disp_w,
            display_height=disp_h,
            has_audio=has_audio,
            audio_rate=int(astream.codec_context.sample_rate) if astream else 0,
            audio_channels=int(astream.codec_context.channels) if astream else 0,
            video_codec=(vstream.codec_context.name or "unknown"),
            audio_codec=(astream.codec_context.name or "unknown") if astream else "none",
            orientation=orientation,
            n_audio_streams=len(astreams),
        )


def has_encoder(name: str) -> bool:
    proc = subprocess.run([ffmpeg(), "-hide_banner", "-encoders"],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return name.encode() in (proc.stdout or b"")
