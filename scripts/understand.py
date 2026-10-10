"""① 理解：把一条口播视频读成结构化事实。

    python3 understand.py --input=某视频.MOV [--job=我的任务] [--model=small]

产出（写进任务目录）：
    analysis.json     全部结构化事实（下游 plan/render 只吃这个）
    transcript.txt    纯净转写
    transcript.srt    字幕
    frames/s_XX.jpg   抽样帧（人脸安全区 + 故事板用）
    audio/voice.wav   16k 单声道口播轨
    brief.md          人类可读的理解简报（agent 在此基础上做创意决策）

原则：**本地处理，视频不出本机**。转写用 faster-whisper（本地），
画面理解用抽帧 + 帧差 + 人脸检测，不调用任何云端模型。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import face as facedet  # noqa: E402
import ffmpeg_bin as ff  # noqa: E402
import motion as motionlib  # noqa: E402
import paths  # noqa: E402

# ── 语义词典（纯启发式打分，不调模型） ──────────────────────────
HOOK_WORDS = ["你", "免费", "揭秘", "真相", "千万", "别", "最", "第一", "为什么",
              "怎么", "一定", "记住", "恭喜", "核心", "关键", "其实", "只要",
              "不用", "直接", "马上", "注意", "小心", "居然"]
CTA_WORDS = ["关注", "点赞", "评论", "私信", "链接", "主页", "报名", "加入",
             "联系", "扫码", "留言", "收藏", "咨询", "合作", "下单"]
NUM_RE = re.compile(r"\d+|[一二三四五六七八九十百千万亿]+")
SENT_END = set("。！？!?…")
CLAUSE = set("，,；;、:")


def log(msg: str) -> None:
    print(msg, flush=True)


# ── 术语表：修正常见 ASR 误听。用户可在 assets/glossary.json 里加自己的行话 ──
DEFAULT_GLOSSARY = {
    "素质员工": "数字员工",
    "职业员工": "数字员工",
    "数字人工程": "数字员工",
    "获课": "获客",
    "私欲": "私域",
    "复购绿": "复购率",
    "转化绿": "转化率",
    "直播待货": "直播带货",
}


def load_glossary() -> dict:
    import json as _json
    table = dict(DEFAULT_GLOSSARY)
    for p in (paths.ASSETS_DIR / "glossary.json", paths.workspace() / "glossary.json"):
        if p.exists():
            try:
                table.update(_json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
    return table


def apply_glossary(text: str, table: dict) -> str:
    for bad, good in sorted(table.items(), key=lambda kv: -len(kv[0])):
        if bad and bad != good:
            text = text.replace(bad, good)
    return text


# ── 音轨 ──────────────────────────────────────────────────────
def extract_audio(video: Path, out_wav: Path, sr: int = 16000) -> Path:
    paths.ensure_dir(out_wav.parent)
    ff.ff("-y", "-i", str(video), "-vn", "-ac", "1", "-ar", str(sr),
          "-c:a", "pcm_s16le", str(out_wav))
    return out_wav


def audio_stats(wav: Path) -> dict:
    with wave.open(str(wav), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if a.size == 0:
        return {"rms_dbfs": -99.0, "peak_dbfs": -99.0, "silences": [], "speech_ratio": 0.0}
    win = max(1, int(sr * 0.05))
    n = a.size // win
    frames = a[: n * win].reshape(n, win) if n else a.reshape(1, -1)
    env = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    dbfs = 20 * np.log10(env + 1e-12)
    thr = -42.0
    silences, start = [], None
    for i, d in enumerate(dbfs):
        if d < thr and start is None:
            start = i
        elif d >= thr and start is not None:
            if (i - start) * 0.05 >= 0.35:
                silences.append([round(start * 0.05, 2), round(i * 0.05, 2)])
            start = None
    if start is not None and (n - start) * 0.05 >= 0.35:
        silences.append([round(start * 0.05, 2), round(n * 0.05, 2)])
    sil_total = sum(b - a for a, b in silences)
    total = a.size / sr
    return {
        "rms_dbfs": round(float(20 * math.log10(float(np.sqrt(np.mean(a ** 2))) + 1e-12)), 2),
        "peak_dbfs": round(float(20 * math.log10(float(np.max(np.abs(a))) + 1e-12)), 2),
        "silences": silences,
        "speech_ratio": round(max(0.0, 1 - sil_total / total), 3) if total else 0.0,
    }


# ── 转写 ──────────────────────────────────────────────────────
def transcribe(wav: Path, model_size: str = "small", lang: str | None = "zh",
               prompt: str | None = None) -> dict:
    from faster_whisper import WhisperModel

    t0 = time.time()
    log(f"  加载模型 faster-whisper/{model_size} …")
    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
    except Exception:
        model = WhisperModel(model_size, device="cpu", compute_type="float32")
    # 加个标点引导词：口播稿没标点的话，下游切句只能按长度硬切，标题会断在半句话上
    if prompt is None:
        prompt = "以下是简体中文短视频口播，请补全标点，写成通顺的句子。"
    segments, info = model.transcribe(
        str(wav), language=lang or None, word_timestamps=True,
        vad_filter=True, beam_size=5, initial_prompt=prompt,
    )
    words, segs = [], []
    for si, seg in enumerate(segments):
        segs.append({"start": round(seg.start, 3), "end": round(seg.end, 3),
                     "text": (seg.text or "").strip()})
        for w in (seg.words or []):
            words.append({"start": round(w.start, 3), "end": round(w.end, 3),
                          "w": w.word, "seg": si})
    log(f"  转写完成：{len(segs)} 段 / {len(words)} 词，用时 {time.time()-t0:.1f}s")
    return {"language": getattr(info, "language", lang) or "zh",
            "model": model_size, "segments": segs, "words": words}


def _join(tokens: list[str], lang: str) -> str:
    if lang.startswith(("zh", "ja", "ko", "th")):
        return "".join(t.strip() for t in tokens)
    return " ".join(t.strip() for t in tokens if t.strip())


def split_sentences(words: list[dict], lang: str, max_chars: int = 30) -> list[dict]:
    """切句优先级：**VAD 段落边界 → 标点 → 长度**。

    只按长度硬切会把标题断在半句话上（"2026年企业省钱最快的方法不是"），
    所以段落边界是第一优先级——它天然落在说话人的换气处。
    """
    out, buf = [], []

    def flush():
        if not buf:
            return
        text = _join([b["w"] for b in buf], lang).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            out.append({"i": len(out), "start": buf[0]["start"], "end": buf[-1]["end"],
                        "text": text, "chars": len(re.sub(r"[^\w\u4e00-\u9fff]", "", text))})
        buf.clear()

    for w in words:
        # 段落边界强制断开
        if buf and w.get("seg") is not None and buf[-1].get("seg") != w.get("seg"):
            flush()
        buf.append(w)
        core = w["w"].strip()
        if not core:
            continue
        tail = core[-1]
        n = sum(len(re.sub(r"[^\w\u4e00-\u9fff]", "", b["w"])) for b in buf)
        if tail in SENT_END:
            flush()
        elif tail in CLAUSE and n >= 12:
            flush()
        elif n >= max_chars:
            flush()
    flush()
    return out


def score_sentence(s: dict, total: int) -> dict:
    text = s["text"]
    hook = sum(1 for w in HOOK_WORDS if w in text)
    cta = sum(1 for w in CTA_WORDS if w in text)
    has_num = bool(NUM_RE.search(text))
    is_q = text.rstrip("，, ").endswith(("吗", "呢", "?", "？"))
    at_edge = s["i"] <= 1 or s["i"] >= total - 2
    ln = s["chars"]
    sc = 0.30 * (1 if has_num else 0) + 0.28 * min(1, hook * 0.6) \
        + 0.18 * (1 if is_q else 0) + 0.14 * (1 if 6 <= ln <= 24 else 0.3) \
        + 0.10 * (0 if at_edge else 1) + 0.12 * min(1, cta)
    tags = []
    if hook:
        tags.append("hook")
    if has_num:
        tags.append("number")
    if cta:
        tags.append("cta")
    if is_q:
        tags.append("question")
    s["score"] = round(min(1.0, sc), 3)
    s["tags"] = tags
    return s


# ── 节拍 ──────────────────────────────────────────────────────
def group_beats(sentences: list[dict], n: int) -> list[dict]:
    """把句子按"说话时长均衡"切成 n 段（DP 最优，边界必落在句子间）。"""
    N = len(sentences)
    n = max(1, min(n, N))
    w = [max(0.4, s["end"] - s["start"]) for s in sentences]
    pre = [0.0]
    for x in w:
        pre.append(pre[-1] + x)
    total = pre[-1]
    target = total / n
    INF = float("inf")
    dp = [[INF] * (n + 1) for _ in range(N + 1)]
    cut = [[0] * (n + 1) for _ in range(N + 1)]
    dp[0][0] = 0.0
    for i in range(1, N + 1):
        for k in range(1, min(i, n) + 1):
            for j in range(k - 1, i):
                seg = pre[i] - pre[j]
                cost = (seg - target) ** 2 / max(1.0, target)
                if dp[j][k - 1] + cost < dp[i][k]:
                    dp[i][k] = dp[j][k - 1] + cost
                    cut[i][k] = j
    bounds, i, k = [], N, n
    while k > 0:
        j = cut[i][k]
        bounds.append((j, i))
        i, k = j, k - 1
    bounds.reverse()

    beats = []
    for k, (a, b) in enumerate(bounds):
        group = sentences[a:b]
        if not group:
            continue
        best = max(group, key=lambda s: s["score"])
        if k == 0:
            tag = "开场"
        elif k == len(bounds) - 1:
            tag = "行动" if any("cta" in s["tags"] for s in group) else "收尾"
        elif any("number" in s["tags"] for s in group):
            tag = "证据"
        else:
            tag = "拆解"
        beats.append({
            "i": k,
            "t0": group[0]["start"],
            "t1": group[-1]["end"],
            "tag": tag,
            "title": best["text"][:18],
            "sentences": [s["i"] for s in group],
            "text": "".join(s["text"] for s in group),
            "hook_score": best["score"],
        })
    return beats


# ── 画面 ──────────────────────────────────────────────────────
def detect_scenes(video: Path, fps_sample: float = 2.5, max_frames: int = 400) -> dict:
    import av

    diffs, times = [], []
    prev = None
    with av.open(str(video)) as c:
        vs = next(s for s in c.streams if s.type == "video")
        rate = float(vs.average_rate) if vs.average_rate else 30.0
        step = max(1, int(round(rate / fps_sample)))
        idx = 0
        for frame in c.decode(vs):
            if idx % step:
                idx += 1
                continue
            idx += 1
            t = float(frame.pts * vs.time_base) if frame.pts is not None else len(times) / fps_sample
            small = frame.reformat(width=64, height=114, format="gray")
            a = np.squeeze(small.to_ndarray()).astype("int16")
            if prev is not None and prev.shape == a.shape:
                diffs.append(float(np.mean(np.abs(a - prev))))
                times.append(round(t, 3))
            prev = a
            if len(times) >= max_frames:
                break
    if not diffs:
        return {"cuts": [], "n_shots": 1, "shots": [[0.0, 0.0]], "avg_diff": 0.0}
    arr = np.asarray(diffs)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med))) + 1e-6
    thr = max(6.0, med + 3.0 * mad)
    cuts = [times[i] for i, d in enumerate(diffs) if d > thr]
    # 合并挨得太近的切点
    merged: list[float] = []
    for ct in cuts:
        if not merged or ct - merged[-1] > 0.7:
            merged.append(ct)
    shots = []
    pts = [0.0] + merged
    for i, s in enumerate(pts):
        e = pts[i + 1] if i + 1 < len(pts) else 0.0
        shots.append([s, e])
    return {"cuts": merged, "n_shots": len(pts), "shots": shots,
            "avg_diff": round(float(arr.mean()), 3), "threshold": round(thr, 3)}


def face_pass(video: Path, duration: float, frames_dir: Path, n: int = 16,
              width: int = 360) -> dict:
    paths.ensure_dir(frames_dir)
    if duration <= 0:
        return {"detected": False, "method": "none", "presence": 0.0, "union_norm": None}
    fps = max(0.2, n / duration)
    ff.ff("-y", "-i", str(video), "-vf", f"fps={fps:.4f},scale={width}:-2",
          "-frames:v", str(n), str(frames_dir / "s_%02d.jpg"))
    frames = sorted(frames_dir.glob("s_*.jpg"))
    if not frames:
        return {"detected": False, "method": "none", "presence": 0.0, "union_norm": None}
    res = facedet.detect_many(frames)
    from PIL import Image

    mw, mh = Image.open(frames[0]).size
    unions, hit = None, 0
    per_frame = []
    for boxes in res["faces"]:
        norm = [[b[0] / mw, b[1] / mh, b[2] / mw, b[3] / mh] for b in boxes]
        per_frame.append(norm)
        if norm:
            hit += 1
        for x, y, w, h in norm:
            if unions is None:
                unions = [x, y, x + w, y + h]
            else:
                unions = [min(unions[0], x), min(unions[1], y),
                          max(unions[2], x + w), max(unions[3], y + h)]
    out = {"detected": unions is not None, "method": res["method"],
           "presence": round(hit / len(frames), 3),
           "n_frames": len(frames), "frame_size": [mw, mh],
           "per_frame": per_frame}
    if unions:
        shrink = facedet.FACE_SHRINK
        cx, cy = (unions[0] + unions[2]) / 2, (unions[1] + unions[3]) / 2
        hw = (unions[2] - unions[0]) / 2 * shrink
        hh = (unions[3] - unions[1]) / 2 * shrink
        out["union_norm"] = [round(cx - hw, 4), round(cy - hh, 4),
                             round(2 * hw, 4), round(2 * hh, 4)]
        # 给 720×1280 舞台用的"不压脸"禁区（外扩 8%）
        x, y, w, h = out["union_norm"]
        ex, ey = w * 0.08, h * 0.08
        out["face_guard_norm"] = [round(max(0, x - ex), 4), round(max(0, y - ey), 4),
                                  round(min(1, w + 2 * ex), 4), round(min(1, h + 2 * ey), 4)]
        out["face_guard_px"] = [round(v * s) for v, s in
                                zip(out["face_guard_norm"], (720, 1280, 720, 1280))]
    return out


# ── 建议 ──────────────────────────────────────────────────────
def recommend(features: dict, duration: float) -> dict:
    n = int(round(duration / 6.0))
    n = max(4, min(8, n))
    rate = features.get("speech_rate") or 0
    if rate >= 5.2:
        bpm = 120
    elif rate >= 4.4:
        bpm = 108
    elif rate >= 3.6:
        bpm = 96
    else:
        bpm = 84
    return {
        "n_beats": n,
        "bpm": bpm,
        "candidates": motionlib.rank({**features, "duration": duration}, top=3),
        "reason": f"时长 {duration:.1f}s → {n} 拍；语速 {rate:.2f} 字/秒 → BGM {bpm} BPM",
    }


def hook_candidates(sentences: list[dict], k: int = 4) -> list[dict]:
    body = [s for s in sentences if 1 < s["i"] < len(sentences) - 1] or sentences
    ranked = sorted(body, key=lambda s: -s["score"])
    return [{"i": s["i"], "text": s["text"], "score": s["score"], "tags": s["tags"]}
            for s in ranked[:k]]


# ── 主流程 ────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="① 理解：把口播视频读成结构化事实")
    ap.add_argument("--input", required=True, help="视频文件路径")
    ap.add_argument("--job", default=None, help="任务名（默认用文件名+时间戳）")
    ap.add_argument("--model", default="small", help="faster-whisper 模型档位 tiny/base/small/medium")
    ap.add_argument("--lang", default="zh", help="语言，auto 为自动判别")
    ap.add_argument("--samples", type=int, default=16, help="人脸检测抽帧数")
    ap.add_argument("--no-transcribe", action="store_true", help="跳过转写（只做画面/音频分析）")
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    info = ff.probe(src)
    log(f"\n素材：{src.name}")
    log(f"  {info.display_width}×{info.display_height} @ {info.fps:g}fps · "
        f"{info.duration:.2f}s · {info.orientation} · 音轨 {'有' if info.has_audio else '无'}"
        + (f" · 旋转 {info.rotation}°" if info.rotation else ""))
    if not info.has_audio:
        log("  ⚠️ 没有音轨：这个 skill 靠口播原声做节奏，无音轨时只能用均分节拍")

    job = paths.ensure_dir(paths.job_dir(args.job) if args.job else paths.new_job(src.stem))
    log(f"任务目录：{job}")

    # 1) 音轨
    wav = extract_audio(src, job / "audio" / "voice.wav")
    a_stats = audio_stats(wav)
    log(f"  音频：RMS {a_stats['rms_dbfs']} dBFS / 峰值 {a_stats['peak_dbfs']} dBFS / "
        f"有声占比 {a_stats['speech_ratio']:.0%} / 停顿 {len(a_stats['silences'])} 处")

    # 2) 转写
    tr = {"language": args.lang, "model": "skipped", "segments": [], "words": []}
    if not args.no_transcribe:
        try:
            tr = transcribe(wav, args.model, None if args.lang == "auto" else args.lang)
        except Exception as exc:  # noqa: BLE001
            log(f"  ⚠️ 转写失败（{type(exc).__name__}: {str(exc)[:90]}），跳过字幕与文案提取")
    lang = tr.get("language") or "zh"
    sentences = split_sentences(tr["words"], lang) if tr["words"] else []
    if not sentences:
        sentences = [{"i": 0, "start": 0.0, "end": round(info.duration, 2),
                      "text": "", "chars": 0}]
    sentences = [score_sentence(s, len(sentences)) for s in sentences]
    gloss = load_glossary()
    fixed = 0
    for s in sentences:
        new = apply_glossary(s["text"], gloss)
        if new != s["text"]:
            s["text"] = new
            fixed += 1
    if fixed:
        log(f"  术语表修正 {fixed} 句（可在 assets/glossary.json 里加你自己的行话）")
    text = "".join(s["text"] for s in sentences)
    numbers = NUM_RE.findall(text)
    speak_dur = sum(max(0.4, s["end"] - s["start"]) for s in sentences)
    speech_rate = round(len(re.sub(r"[^\w\u4e00-\u9fff]", "", text)) / speak_dur, 2) if speak_dur else 0.0
    log(f"  文案：{len(sentences)} 句 / {len(text)} 字 / 语速 {speech_rate} 字每秒")

    # 3) 画面
    scenes = detect_scenes(src)
    log(f"  画面：{scenes['n_shots']} 个镜头段（切点 {len(scenes['cuts'])} 处，阈值 {scenes.get('threshold')}）")
    fp = face_pass(src, info.duration, job / "frames", n=args.samples)
    if fp["detected"]:
        log(f"  人脸：检出（{fp['method']}，{fp['presence']:.0%} 的抽样帧有脸），"
            f"禁区(720×1280) {fp['face_guard_px']}")
    else:
        log(f"  人脸：未检出（{fp['method']}）→ 图形可占整屏，但仍建议压在下方 2/3")

    # 4) 节拍 + 建议
    rec0 = int(round(info.duration / 6.0))
    beats = group_beats(sentences, max(4, min(8, rec0)))
    features = {"text": text, "numbers": numbers, "speech_rate": speech_rate,
                "orientation": info.orientation, "has_face": fp["detected"]}
    rec = recommend(features, info.duration)

    analysis = {
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "job": job.name,
        "source": str(src),
        "media": info.as_dict(),
        "audio_stats": a_stats,
        "transcript": {"language": lang, "model": tr.get("model"),
                       "segments": tr.get("segments", []), "sentences": sentences},
        "text": text,
        "beats": beats,
        "scenes": scenes,
        "face": fp,
        "recommend": rec,
        "hooks": hook_candidates(sentences),
    }
    (job / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    (job / "transcript.txt").write_text(text + "\n", encoding="utf-8")
    write_srt(job / "transcript.srt", sentences)
    write_brief(job / "brief.md", analysis, info, src)

    log(f"\n✅ 理解完成 → {job}")
    log(f"   analysis.json   结构化事实")
    log(f"   brief.md        理解简报（含剪辑建议）")
    log(f"   transcript.txt / .srt")
    log(f"   frames/         抽样帧 {fp.get('n_frames', 0)} 张")
    log(f"\n建议：{rec['reason']}")
    log(f"动效候选：" + " / ".join(f"{c['name']}({c['id']} score={c['score']})" for c in rec["candidates"]))
    log(f"\n下一步：python3 plan.py --job={job.name}")
    return 0


def write_srt(path: Path, sentences: list[dict]) -> None:
    def ts(t: float) -> str:
        h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")

    lines = []
    for i, s in enumerate(sentences, 1):
        if not s["text"]:
            continue
        lines += [str(i), f"{ts(s['start'])} --> {ts(s['end'])}", s["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_brief(path: Path, a: dict, info, src: Path) -> None:
    L: list[str] = []
    m = a["media"]
    L += [f"# 理解简报 · {src.name}", ""]
    L += [f"- 规格：**{m['display_width']}×{m['display_height']}** @ {m['fps']:g}fps，"
          f"{m['duration']:.2f}s，{m['orientation']}",
          f"- 音轨：{m['video_codec']} / 音频 {m['audio_codec']} "
          f"{m['audio_rate']}Hz ×{m['audio_channels']}",
          f"- 音频：RMS **{a['audio_stats']['rms_dbfs']} dBFS**，峰值 {a['audio_stats']['peak_dbfs']} dBFS，"
          f"有声占比 {a['audio_stats']['speech_ratio']:.0%}，停顿 {len(a['audio_stats']['silences'])} 处",
          f"- 画面：**{a['scenes']['n_shots']} 个镜头段**，切点 {len(a['scenes']['cuts'])} 处",
          f"- 人脸：{'检出' if a['face']['detected'] else '未检出'}"
          f"（{a['face']['method']}，{a['face'].get('presence', 0):.0%} 抽样帧有脸）", ""]
    if a["face"].get("face_guard_px"):
        L += [f"  → 不压脸禁区（720×1280）：x={a['face']['face_guard_px'][0]}, y={a['face']['face_guard_px'][1]}, "
              f"w={a['face']['face_guard_px'][2]}, h={a['face']['face_guard_px'][3]}", ""]
    L += ["## 口播转写（分句 · 时间轴）", ""]
    for s in a["transcript"]["sentences"]:
        mark = " ⭐" if s["score"] >= 0.6 else ""
        L.append(f"- `{s['start']:6.2f}–{s['end']:6.2f}` {s['text']}{mark}")
    L += ["", "## 剪辑节拍建议", "",
          f"语速 {a['recommend']['reason']}", "",
          "| # | 时段 | 标签 | 建议标题 |", "|---|---|---|---|"]
    for b in a["beats"]:
        L.append(f"| {b['i']+1} | {b['t0']:.2f}–{b['t1']:.2f}s | {b['tag']} | {b['title']} |")
    L += ["", "## 钩子候选（大字文案素材）", ""]
    for h in a["hooks"]:
        L.append(f"- 〔{h['score']}〕{h['text']}  {'·' + '/'.join(h['tags']) if h['tags'] else ''}")
    L += ["", "## 动效候选", ""]
    for c in a["recommend"]["candidates"]:
        L.append(f"- **{c['name']}**（`{c['id']}`，冲击力 {c['impact']}/5，得分 {c['score']}）：{c['summary']}")
        if c.get("hits"):
            L.append(f"  - 命中关键词：{'、'.join(c['hits'][:6])}")
    L += ["", "## 待人工确认", "",
          "- [ ] 数字/事实是否可对外（转写可能有误，尤其公司名与金额）",
          "- [ ] 是否使用 BGM（默认按 BPM 合成无版权配乐）",
          "- [ ] 是否需要配图/B-roll（默认只用动效层，不引入外部素材）",
          "- [ ] 封面大字取哪一句", ""]
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
