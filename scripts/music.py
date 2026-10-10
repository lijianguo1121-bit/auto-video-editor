"""配乐合成（纯 numpy，无版权素材）。

不是随机噪声：按 BPM 网格铺一层 pad 和弦 + 底鼓 + 高频点缀，
再用**口播人声包络做侧链**——人一说话音乐自动退让，这是"听着不吵"的关键。

    python3 music.py --out=music.wav --duration=29.4 --bpm=96 --voice=audio/voice.wav
"""
from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100


def _env_duck(voice_wav: Path | None, duration: float, smooth: float = 0.25) -> np.ndarray:
    """从口播轨算出一条 0→1 的"人声活动"曲线，用来压低音乐。"""
    n = int(duration * SR)
    if not voice_wav or not Path(voice_wav).exists():
        return np.zeros(n, dtype=np.float32)
    with wave.open(str(voice_wav), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if a.size == 0:
        return np.zeros(n, dtype=np.float32)
    win = max(1, int(sr * 0.03))
    m = a.size // win
    env = np.sqrt(np.mean(a[: m * win].reshape(m, win) ** 2, axis=1) + 1e-12)
    act = np.clip((20 * np.log10(env + 1e-12) + 46) / 22, 0, 1)      # -46dB→0, -24dB→1
    # 上采样到采样率 + 平滑
    idx = np.linspace(0, m - 1, max(1, n))
    up = np.interp(idx, np.arange(m), act).astype(np.float32)
    k = max(1, int(smooth * SR))
    ker = np.hanning(k); ker /= ker.sum()
    return np.convolve(up, ker, mode="same").astype(np.float32)


def _tone(freq: float, dur: float, sr: int = SR) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    return np.sin(2 * np.pi * freq * t)


def synth(duration: float, bpm: int, voice_wav: Path | None = None,
          mood: str = "warm") -> np.ndarray:
    n = int(duration * SR)
    beat = 60.0 / bpm
    out = np.zeros(n, dtype=np.float32)

    # 和弦进行（小调温暖）：Am - F - C - G
    chords = {
        "warm": [[220.0, 261.6, 329.6], [174.6, 220.0, 261.6],
                 [261.6, 329.6, 392.0], [196.0, 246.9, 293.7]],
        "bright": [[261.6, 329.6, 392.0], [293.7, 370.0, 440.0],
                   [329.6, 415.3, 493.9], [349.2, 440.0, 523.3]],
    }[mood if mood in ("warm", "bright") else "warm"]

    bar = beat * 4
    nbars = int(np.ceil(duration / bar)) + 1
    for b in range(nbars):
        chord = chords[b % len(chords)]
        t0 = int(b * bar * SR)
        seg_len = int(bar * SR)
        if t0 >= n:
            break
        seg = np.zeros(min(seg_len, n - t0), dtype=np.float32)
        for f in chord:
            tone = _tone(f, len(seg) / SR)
            tone += 0.5 * _tone(f * 2, len(seg) / SR)          # 一点泛音
            seg += tone[: len(seg)].astype(np.float32) * 0.16
        # 每小节的柔和起音
        atk = int(0.35 * SR)
        seg[:min(atk, len(seg))] *= np.linspace(0, 1, min(atk, len(seg))) ** 0.6
        out[t0: t0 + len(seg)] += seg

    # 底鼓（每拍）+ 高频点缀（反拍）
    t = np.arange(n) / SR
    for k in range(int(duration / beat) + 1):
        st = int(k * beat * SR)
        if st >= n:
            break
        ln = min(int(0.16 * SR), n - st)
        tt = np.arange(ln) / SR
        kick = np.sin(2 * np.pi * (58 * np.exp(-tt * 22) + 40) * tt) * np.exp(-tt * 16)
        out[st: st + ln] += (kick * 0.34).astype(np.float32)
        if k % 2 == 1:
            st2 = int((k * beat + beat * 0.5) * SR)
            ln2 = min(int(0.05 * SR), n - st2)
            if st2 + ln2 <= n and ln2 > 0:
                tt2 = np.arange(ln2) / SR
                hat = np.random.RandomState(k).randn(ln2).astype(np.float32) * np.exp(-tt2 * 90)
                out[st2: st2 + ln2] += hat * 0.05

    # 侧链：人声在说话 → 音乐退让到 30%
    duck = _env_duck(voice_wav, duration)
    out *= (1.0 - 0.7 * duck)

    # 头尾淡入淡出
    fi, fo = int(0.8 * SR), int(1.2 * SR)
    if n > fi + fo:
        out[:fi] *= np.linspace(0, 1, fi) ** 0.7
        out[-fo:] *= np.linspace(1, 0, fo) ** 0.9
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.62).astype(np.float32)


def write_wav(path: Path, data: np.ndarray, sr: int = SR) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(data, -1, 1)
    pcm = (pcm * 32767).astype("<i2")
    stereo = np.repeat(pcm.reshape(-1, 1), 2, axis=1).tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(stereo)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--bpm", type=int, default=96)
    ap.add_argument("--mood", default="warm", choices=["warm", "bright"])
    ap.add_argument("--voice", default=None, help="口播轨（用于侧链退让）")
    args = ap.parse_args()
    data = synth(args.duration, args.bpm,
                 Path(args.voice) if args.voice else None, args.mood)
    out = write_wav(Path(args.out), data)
    print(f"配乐已生成：{out}（{args.duration:.1f}s / {args.bpm} BPM / {args.mood}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
