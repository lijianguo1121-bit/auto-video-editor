"""③ 渲染：逐帧动效层 + 原片 → 成片（+ 封面）。

    python3 render.py --job=demo1 [--styles=route,impact] [--export=~/Downloads/xxx]

做四件事：
    1) 把原片规整成 720×1280 的"底片"（竖屏原片直接缩放，横屏加模糊底衬不裁画面）
    2) 配乐（可选，按 BPM 合成；人声一说话自动退让）
    3) 动效层逐帧抓屏 → **直接灌给 ffmpeg 的 stdin** → 一次出片，峰值磁盘占用≈0
    4) 音频两步法响度归一（先量后补 + 限幅），最后拼封面

为什么不用中间帧文件：一套 30s 的 720×1280 alpha 帧序列能到 1GB+，
本机磁盘常年只剩几个 GB，落盘必然把磁盘打满（表现为浏览器莫名崩溃）。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cover as covermod  # noqa: E402
import ffmpeg_bin as ff  # noqa: E402
import music as musicmod  # noqa: E402
import paths  # noqa: E402
from capture import MotionStage  # noqa: E402
from plan import motion_cfg  # noqa: E402


def log(m: str) -> None:
    print(m, flush=True)


# ── 底片 ─────────────────────────────────────────────────────
def build_base(src: Path, info, out: Path, w: int, h: int, fit: str = "auto") -> Path:
    ar_src = info.display_width / max(1, info.display_height)
    ar_dst = w / h
    mode = fit
    if fit == "auto":
        mode = "blur" if abs(ar_src - ar_dst) > 0.22 else "cover"
    if mode == "blur":
        vf = (f"split=2[bg][fg];"
              f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=30[bgb];"
              f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fgs];"
              f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,format=yuv420p")
    else:
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},format=yuv420p"
    ff.ff("-y", "-i", str(src), "-vf", vf, "-an",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(out))
    log(f"  底片：{w}×{h}（{mode}）→ {out.name}")
    return out


# ── 音频 ─────────────────────────────────────────────────────
def _loudnorm_measure(wav: Path, i: float, tp: float, lra: float) -> dict:
    proc = subprocess.run(
        [ff.ffmpeg(), "-hide_banner", "-i", str(wav),
         "-af", f"loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json",
         "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    err = (proc.stderr or b"").decode("utf-8", "replace")
    blocks = re.findall(r"\{[\s\S]*?\}", err)
    for b in reversed(blocks):
        try:
            d = json.loads(b)
            if "input_i" in d:
                return d
        except Exception:
            continue
    return {}


def build_audio(src: Path, music: Path | None, duration: float, out_m4a: Path,
                lufs: float = -15.0, tp: float = -1.7, music_vol: float = 0.30,
                work: Path | None = None) -> dict:
    """口播为主轨；有配乐就混进来（配乐已自带侧链退让）；两步法响度归一。"""
    work = work or out_m4a.parent
    tmp = work / "_mix.wav"
    if music and music.exists():
        fc = (f"[0:a]aresample=48000,volume=1.0[v];"
              f"[1:a]aresample=48000,volume={music_vol},atrim=0:{duration:.3f}[m];"
              f"[v][m]amix=inputs=2:duration=first:normalize=0[mix]")
        ff.ff("-y", "-i", str(src), "-i", str(music), "-filter_complex", fc,
              "-map", "[mix]", "-c:a", "pcm_s16le", "-ar", "48000", str(tmp))
    else:
        ff.ff("-y", "-i", str(src), "-vn", "-ac", "2", "-ar", "48000",
              "-c:a", "pcm_s16le", str(tmp))

    m = _loudnorm_measure(tmp, lufs, tp, 11.0)
    measured = ""
    if m:
        # 注意：loudnorm 的选项名大小写敏感，且 offset 不叫 measured_offset
        for opt, key in (("measured_I", "input_i"), ("measured_TP", "input_tp"),
                         ("measured_LRA", "input_lra"), ("measured_thresh", "input_thresh"),
                         ("offset", "target_offset")):
            if m.get(key) is not None:
                measured += f":{opt}={m[key]}"
    af = f"loudnorm=I={lufs}:TP={tp}:LRA=11{measured}:linear=true,alimiter=limit=0.94"
    ff.ff("-y", "-i", str(tmp), "-af", af, "-c:a", "aac", "-b:a", "192k",
          "-ar", "48000", "-ac", "2", str(out_m4a))
    try:
        tmp.unlink()
    except Exception:
        pass
    log(f"  音频：响度归一 → {lufs} LUFS / 峰值 {tp} dBFS" +
        (f"（实测 in={m.get('input_i')} LUFS）" if m else "（未取到实测值，走单次归一）"))
    return m


# ── 逐帧渲染 ─────────────────────────────────────────────────
def render_style(plan: dict, style: str, base: Path, audio: Path | None,
                 out_path: Path, work: Path, fps: int, crf: int, preset: str,
                 max_seconds: float | None = None) -> Path:
    cfg = motion_cfg(plan)
    cfg["style"] = style
    duration = float(plan["duration"])
    if max_seconds:
        duration = min(duration, float(max_seconds))
        cfg["duration"] = duration
        cfg["beats"] = [b for b in cfg["beats"] if b["t0"] < duration]
        if cfg["beats"]:
            cfg["beats"][-1]["t1"] = max(cfg["beats"][-1]["t1"], duration)

    n_frames = max(1, int(round(duration * fps)))
    silent = work / f"_{style}_silent.mp4"
    t0 = time.time()
    log(f"  ── {style} ── 逐帧 {n_frames} 帧 @ {fps}fps")

    cmd = [ff.ffmpeg(), "-y", "-i", str(base),
           "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
           "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[v]",
           "-map", "[v]", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-r", str(fps), str(silent)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        with MotionStage(cfg) as st:
            for i in range(n_frames):
                t = i / fps
                png = st.frame(t)
                proc.stdin.write(png)
                if (i + 1) % max(1, n_frames // 8) == 0 or i == n_frames - 1:
                    el = time.time() - t0
                    eta = el / (i + 1) * (n_frames - i - 1)
                    log(f"     {i+1}/{n_frames}  {el:.0f}s  ETA {eta:.0f}s")
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        err = proc.stderr.read() if proc.stderr else b""
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"合成失败({rc})：{err.decode('utf-8','replace')[-1200:]}")

    if audio and audio.exists():
        ff.ff("-y", "-i", str(silent), "-i", str(audio),
              "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "copy",
              "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out_path))
    else:
        ff.ff("-y", "-i", str(silent), "-c", "copy", "-movflags", "+faststart", str(out_path))
    try:
        silent.unlink()
    except Exception:
        pass
    log(f"  成片 {out_path.name}  用时 {time.time()-t0:.0f}s  "
        f"{out_path.stat().st_size/1e6:.1f}MB")
    return out_path


# ── 质检 ─────────────────────────────────────────────────────
def _env(wav: Path, sr: int = 8000, win: float = 0.05) -> np.ndarray:
    with wave.open(str(wav), "rb") as w:
        r = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    n = a.size // max(1, int(r * win))
    if n < 2:
        return np.zeros(1, dtype=np.float32)
    return np.sqrt(np.mean(a[: n * int(r * win)].reshape(n, -1) ** 2, axis=1))


def qa(src: Path, out: Path, job: Path) -> dict:
    a = job / "_qa_src.wav"
    b = job / "_qa_out.wav"
    ff.ff("-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", str(a))
    ff.ff("-y", "-i", str(out), "-vn", "-ac", "1", "-ar", "8000", "-c:a", "pcm_s16le", str(b))
    e1, e2 = _env(a), _env(b)
    n = min(e1.size, e2.size)
    corr = float(np.corrcoef(e1[:n], e2[:n])[0, 1]) if n > 4 else float("nan")
    info = ff.probe(out)
    res = {"duration": info.duration, "size": [info.display_width, info.display_height],
           "fps": info.fps, "has_audio": info.has_audio,
           "audio_preserved_corr": round(corr, 4)}
    for f in (a, b):
        try:
            f.unlink()
        except Exception:
            pass
    return res


# ── 主流程 ───────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="③ 渲染：出成片 + 封面")
    ap.add_argument("--job", required=True)
    ap.add_argument("--styles", default="", help="覆盖动效（逗号分隔）；默认用 plan.json 里的 style")
    ap.add_argument("--fps", type=int, default=0, help="输出帧率，默认 30")
    ap.add_argument("--crf", type=int, default=0)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--fit", default="auto", choices=["auto", "cover", "blur"])
    ap.add_argument("--max-seconds", type=float, default=0, help="只渲前 N 秒，用来快速试片")
    ap.add_argument("--no-bgm", action="store_true")
    ap.add_argument("--no-cover", action="store_true")
    ap.add_argument("--export", default="", help="把成片与封面拷到指定目录")
    args = ap.parse_args()

    job = paths.job_dir(args.job)
    pj = job / "plan.json"
    aj = job / "analysis.json"
    if not pj.exists() or not aj.exists():
        log(f"❌ 缺少 plan.json / analysis.json（{job}）\n   先跑 understand.py 再跑 plan.py")
        return 1
    plan = json.loads(pj.read_text(encoding="utf-8"))
    analysis = json.loads(aj.read_text(encoding="utf-8"))
    src = Path(analysis["source"])
    info = ff.probe(src)

    fps = args.fps or int(plan["render"]["fps"])
    crf = args.crf or int(plan["render"]["crf"])
    W, H = int(plan["render"]["width"]), int(plan["render"]["height"])
    styles = [s.strip() for s in args.styles.split(",") if s.strip()] or [plan["style"]]

    work = paths.ensure_dir(job / "work")
    out_dir = paths.ensure_dir(job / "out")

    log(f"\n渲染任务 {job.name}：{src.name} · {info.duration:.2f}s → {W}×{H} @{fps}fps")
    base = build_base(src, info, work / "base.mp4", W, H, args.fit)

    # BGM
    music_path = None
    if plan["bgm"]["on"] and not args.no_bgm:
        music_path = job / "audio" / "music.wav"
        if not music_path.exists():
            log(f"  合成配乐 {plan['bgm']['bpm']} BPM（{plan['bgm']['mood']}，含人声侧链退让）…")
            data = musicmod.synth(plan["duration"], plan["bgm"]["bpm"],
                                  job / "audio" / "voice.wav", plan["bgm"]["mood"])
            musicmod.write_wav(music_path, data)
        else:
            log(f"  复用已有配乐 {music_path.name}")
    audio = build_audio(src, music_path, plan["duration"], job / "audio" / "mix.m4a",
                        lufs=float(plan["render"]["loudness_lufs"]), work=work)

    results = []
    for i, style in enumerate(styles, 1):
        out_path = out_dir / f"{i:02d}_{style}.mp4"
        render_style(plan, style, base, job / "audio" / "mix.m4a", out_path, work,
                     fps, crf, args.preset, args.max_seconds or None)
        results.append(out_path)

    covers = []
    if not args.no_cover:
        log("  生成封面 …")
        try:
            covers = covermod.make_covers(job, plan, results[0])
            for c in covers:
                log(f"     {c.name}")
        except Exception as exc:  # noqa: BLE001
            log(f"     ⚠️ 封面失败（不影响成片）：{type(exc).__name__}: {str(exc)[:120]}")

    log("\n质检：")
    for r in results:
        q = qa(src, r, work)
        log(f"  {r.name}  {q['size'][0]}×{q['size'][1]} @{q['fps']:.2f}fps  {q['duration']:.2f}s  "
            f"音轨{'有' if q['has_audio'] else '无'}  原声保留相关 {q['audio_preserved_corr']}"
            + ("  ✅" if q["audio_preserved_corr"] > 0.93 else "  ⚠️ 原声可能被动了，查一下"))

    if args.export:
        dest = Path(args.export).expanduser()
        paths.ensure_dir(dest)
        for r in results:
            shutil.copy2(r, dest / r.name)
        if covers:
            cdir = paths.ensure_dir(dest / "covers")
            for c in covers:
                shutil.copy2(c, cdir / c.name)
        log(f"\n已导出 → {dest}")

    log(f"\n完成：")
    for r in results:
        log(f"  {r}")
    log("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
