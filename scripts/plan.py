"""② 编排：把"理解"变成可执行的剪辑方案 + 故事板预览。

    python3 plan.py --job=demo1 [--style=route] [--brand-name=IMAI] [...]

产出（写进任务目录）：
    plan.json                  渲染配置（render.py 只吃这个）
    plan.md                    人类可读的创作方案
    previews/beat_XX.png       每拍代表帧
    previews/storyboard.png    故事板总览（拼版）
    previews/storyboard.html   可点开的故事板（浏览器里看）

设计立场：脚本负责**事实与默认值**，创意判断交给 agent / 人。
所以 plan.json 是纯数据、可手改；改完直接 render 就能出新片子。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import motion as motionlib  # noqa: E402
import paths  # noqa: E402
import understand as U  # noqa: E402

FILLER = ["那个", "这个", "然后", "就是", "其实", "所以说", "那么", "对吧",
          "你知道", "我们", "就是说", "然后呢", "呢", "啊", "吧"]
UNIT_WORDS = ["座", "个", "家", "万", "亿", "%", "倍", "天", "年", "次", "元",
              "人", "条", "台", "套", "小时", "分钟", "单", "门店", "城市", "客户", "员工", "学员"]


def log(m: str) -> None:
    print(m, flush=True)


# ── 文案打磨 ─────────────────────────────────────────────────
def _clauses(text: str) -> list[str]:
    parts = re.split(r"[，,。；;、!！?？…\s]+", text or "")
    return [p.strip() for p in parts if len(p.strip()) >= 2]


def _clause_score(c: str) -> float:
    s = 0.0
    if re.search(r"\d", c):
        s += 2.0
    s += 0.8 * sum(1 for w in U.HOOK_WORDS if w in c)
    s += 1.0 * sum(1 for w in U.CTA_WORDS if w in c)
    s += 0.5 if 5 <= len(c) <= 14 else -0.4
    return s


DANGLING = ["不是", "就是", "然后", "还有", "但是", "因为", "所以", "也就是说",
            "的", "把", "让", "我", "你", "这", "那", "是", "和", "跟", "了"]


UNIT_CHARS = "万亿%倍座个家台条次天年元人份款项步期时小分秒"


def blocks(text: str) -> list[tuple[str, str]]:
    """把句子切成"语义块"：数字+单位 / 英文串 / 标点 / 汉字（2 字一组）。

    硬截断会把"客服销售"切成"客服销"，所以截断一律以块为单位。
    """
    out: list[tuple[str, str]] = []
    i, s = 0, text or ""
    while i < len(s):
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit():
            j = i
            while j < len(s) and (s[j].isdigit() or s[j] in ".,"):
                j += 1
            if j < len(s) and s[j] in UNIT_CHARS:
                j += 1
            out.append((s[i:j], "num"))
            i = j
            continue
        if ch.isascii() and ch.isalpha():
            j = i
            while j < len(s) and s[j].isascii() and s[j].isalnum():
                j += 1
            out.append((s[i:j], "latin"))
            i = j
            continue
        if ch in "，。！？、；：,.!?;:·—-~～":
            out.append((ch, "punct"))
            i += 1
            continue
        out.append((s[i:i + 2], "cjk"))
        i += 2
    return out


def smart_trim(text: str, max_len: int) -> str:
    """在 max_len 内取"信息量最足"的连续块窗口，而不是从头上砍一刀。"""
    bs = blocks(text)
    whole = "".join(b for b, _ in bs)
    if len(whole) <= max_len:
        return whole
    best: tuple[float, str] | None = None
    for a in range(len(bs)):
        cur: list[tuple[str, str]] = []
        for b in bs[a:]:
            if sum(len(x) for x, _ in cur) + len(b) > max_len:
                break
            cur.append(b)
            cand = "".join(x for x, _ in cur)
            score = 0.0
            for blk, kind in cur:
                if kind in ("num", "latin"):
                    score += 0.75
                if any(w in blk for w in U.HOOK_WORDS):
                    score += 0.35
            score += 0.30 * len(cand) / max(1, max_len)
            if cur[-1][1] == "punct":
                score -= 0.5
            if best is None or score > best[0]:
                best = (score, cand)
    out = best[1] if best else whole[:max_len]
    return out.strip("，。！？、；：,.!?;: ")


def pick_title(beat: dict, max_len: int = 16) -> tuple[str, str]:
    cs = _clauses(beat.get("text", ""))
    if not cs:
        return beat.get("tag", "正文"), ""
    # 优先挑"截得下也不太短"的那句
    def total_score(c: str) -> float:
        s = _clause_score(c)
        if len(c) > max_len:
            s -= 1.2
        if len(c) < 4:
            s -= 1.0
        return s
    ranked = sorted(cs, key=total_score, reverse=True)
    head = ranked[0]
    for f in FILLER:
        head = head.replace(f, "")
    # 掐掉尾巴上的悬空词（"…的方法不是" 这种读着断气）
    changed = True
    while changed and len(head) > 5:
        changed = False
        for d in DANGLING:
            if head.endswith(d) and len(head) - len(d) >= 4:
                head = head[: -len(d)]
                changed = True
    head = smart_trim(head, max_len)
    head = head.strip("，。！？、 的") or smart_trim(ranked[0], max_len)
    sub = ""
    for c in ranked[1:]:
        if c[:6] not in head and len(c) >= 3:
            sub = smart_trim(c, 18)
            break
    return head, sub


def pick_metric(text: str, n_beats: int) -> dict:
    """挑一个适合当"主指标"的数字。

    规则：跳过年份（2026 年），带单位的数字加权，量级大的优先。
    """
    best = None
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*([万亿]?)", text or ""):
        raw = float(m.group(1))
        tail = (text or "")[m.end(): m.end() + 3]
        if tail.startswith("年") and 1900 <= raw <= 2100:
            continue                                  # 年份不是成绩
        mult = 10000.0 if m.group(2) == "万" else 1e8 if m.group(2) == "亿" else 1.0
        # "200 万" 这种：单位在后面
        if not m.group(2):
            nm = re.match(r"\s*([万亿])", (text or "")[m.end(): m.end() + 2])
            if nm:
                mult = 10000.0 if nm.group(1) == "万" else 1e8
        val = raw * mult
        unit = next((u for u in UNIT_WORDS if tail.startswith(u)), "")
        score = (2.0 if unit else 0.0) + (1.0 if mult > 1 else 0.0) + (0.6 if val >= 10 else 0.0)
        if best is None or score > best[0] or (score == best[0] and val > best[1]):
            best = (score, val, unit)
    if not best or best[1] <= 0:
        return {"value": n_beats, "unit": "个要点"}
    val = int(best[1]) if float(best[1]).is_integer() else round(best[1], 1)
    return {"value": val, "unit": best[2] or "个"}


# ── 方案构建 ─────────────────────────────────────────────────
def build_plan(a: dict, args) -> dict:
    style = args.style or (a["recommend"]["candidates"][0]["id"]
                           if a["recommend"].get("candidates") else "route")
    meta = motionlib.get(style) or motionlib.get("route")
    duration = float(a["media"]["duration"])
    fps = float(a["media"]["fps"])

    # 节拍：可覆盖数量
    beats_src = a["beats"]
    if args.beats:
        sentences = a["transcript"]["sentences"]
        beats_src = U.group_beats(sentences, max(1, int(args.beats)))

    max_len = {"impact": 9, "editorial": 18, "route": 14}.get(style, 16)
    beats = []
    for b in beats_src:
        title, sub = pick_title(b, max_len)
        beats.append({"i": b["i"], "t0": round(b["t0"], 3), "t1": round(b["t1"], 3),
                      "tag": b["tag"], "title": title, "sub": sub,
                      "text": b.get("text", "")})

    # 品牌
    brand = {
        "name": args.brand_name or "",
        "tagline": args.brand_tagline or "",
        "cta": args.brand_cta or "",
    }

    # 配色：默认取动效自带；--palette 可覆盖 a,b,c
    pal = dict(zip(("a", "b", "c"), meta["palette"][1:])) if len(meta["palette"]) >= 4 else {}
    pal.setdefault("a", meta["palette"][1] if len(meta["palette"]) > 1 else "#8DE0C2")
    pal.setdefault("b", meta["palette"][2] if len(meta["palette"]) > 2 else "#F5F2E9")
    pal.setdefault("c", meta["palette"][3] if len(meta["palette"]) > 3 else "#FF9B79")
    pal["bg"] = meta["palette"][0] if meta["palette"] else "#0B1116"
    pal["ink"] = pal["b"]
    if args.palette:
        over = [p.strip() for p in args.palette.split(",") if p.strip()]
        for k, v in zip(("a", "b", "c"), over):
            pal[k] = v

    # 钩子 & 路线节点
    text = a.get("text", "")
    hook = args.hook or (a["hooks"][0]["text"] if a.get("hooks") else "")
    if hook:
        for f in FILLER:
            hook = hook.replace(f, "")
        hook = hook.strip()[:18]
    if args.nodes:
        nodes = [n.strip() for n in re.split(r"[,\s|，、]+", args.nodes) if n.strip()][:6]
    else:
        nodes = []          # 没给就不硬凑标签，航线只走光点；给 --nodes 才显示城市/阶段名

    plan = {
        "version": 1,
        "job": a.get("job"),
        "style": style,
        "style_name": meta["name"],
        "duration": duration,
        "fps": round(fps, 4),
        "brand": brand,
        "palette": pal,
        "hud": {"pill": bool(brand["name"]), "progress": True},
        "face": a.get("face", {}),
        "beats": beats,
        "copy": {
            "hook": hook,
            "metric": pick_metric(text, len(beats)),
            "cta": brand["cta"],
        },
        "route": {"nodes": nodes},
        "motion": {"enter": 0.28, "out": 0.16, "speed": 1.0},
        "bgm": {"on": not args.no_bgm, "bpm": int(args.bpm or a["recommend"].get("bpm", 96)),
                "mood": "bright" if style == "impact" else "warm"},
        "render": {"width": 720, "height": 1280, "fps": 30, "crf": 19,
                   "preset": "medium", "loudness_lufs": -15.0, "audio_bitrate": "192k"},
        "alternatives": [{k: v for k, v in c.items() if k in ("id", "name", "summary", "score", "hits")}
                         for c in a["recommend"].get("candidates", [])],
    }
    return plan


def motion_cfg(plan: dict) -> dict:
    """把 plan 转成动效层吃得下的 CFG。"""
    return {
        "style": plan["style"], "fps": plan["fps"], "duration": plan["duration"],
        "brand": plan["brand"], "palette": plan["palette"], "hud": plan["hud"],
        "face": {"detected": bool(plan["face"].get("detected")),
                 "guard_px": plan["face"].get("face_guard_px")},
        "beats": [{"i": b["i"], "t0": b["t0"], "t1": b["t1"], "tag": b["tag"],
                   "title": b["title"], "sub": b["sub"]} for b in plan["beats"]],
        "copy": plan["copy"], "route": plan["route"], "motion": plan["motion"],
    }


# ── 故事板 ───────────────────────────────────────────────────
def _font(size: int):
    from PIL import ImageFont

    for p in ("/System/Library/Fonts/PingFang.ttc",
              "/System/Library/Fonts/STHeiti Medium.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def storyboard(plan: dict, job: Path, scale: float = 0.32) -> Path | None:
    from PIL import Image, ImageDraw

    from capture import MotionStage

    cfg = motion_cfg(plan)
    out_dir = paths.ensure_dir(job / "previews")
    cells = []
    with MotionStage(cfg) as st:
        for b in plan["beats"]:
            t = b["t0"] + (b["t1"] - b["t0"]) * 0.55
            png = st.frame(t)
            fp = out_dir / f"beat_{b['i']+1:02d}.png"
            fp.write_bytes(png)
            cells.append((fp, b))
        # 封面代表帧：钩子出现那一刻
        st.frame(max(0.0, plan["duration"] * 0.02))

    cw, ch = int(720 * scale), int(1280 * scale)
    gap, pad, label_h = 16, 28, 64
    cols = min(5, max(1, len(cells)))
    rows = math.ceil(len(cells) / cols)
    header = 118
    W = pad * 2 + cols * cw + (cols - 1) * gap
    H = header + pad + rows * (ch + label_h + gap)
    sheet = Image.new("RGB", (W, H), (14, 17, 22))
    d = ImageDraw.Draw(sheet)
    f_title, f_sub, f_lab, f_val = _font(30), _font(17), _font(20), _font(16)

    d.text((pad, 26), f"故事板 · {plan['style_name']}（{plan['style']}）", font=f_title, fill=(238, 236, 229))
    d.text((pad, 68),
           f"{plan['duration']:.1f}s · {len(plan['beats'])} 拍 · "
           f"BGM {plan['bgm']['bpm']}BPM({'开' if plan['bgm']['on'] else '关'}) · "
           f"人脸{'已锁定安全区' if plan['face'].get('detected') else '未检出'}",
           font=f_sub, fill=(150, 158, 168))

    for i, (fp, b) in enumerate(cells):
        r, c = divmod(i, cols)
        x = pad + c * (cw + gap)
        y = header + pad + r * (ch + label_h + gap)
        im = Image.open(fp).convert("RGB")
        im = im.resize((cw, ch), Image.LANCZOS)
        sheet.paste(im, (x, y))
        d.rectangle([x, y, x + cw - 1, y + ch - 1], outline=(60, 68, 78))
        d.text((x, y + ch + 8), f"{b['i']+1:02d} · {b['tag']}", font=f_val, fill=(141, 224, 194))
        d.text((x, y + ch + 30), b["title"][:14], font=f_lab, fill=(238, 236, 229))

    sheet_path = out_dir / "storyboard.png"
    sheet.save(sheet_path)
    write_storyboard_html(plan, out_dir, cells)
    return sheet_path


def write_storyboard_html(plan: dict, out_dir: Path, cells) -> Path:
    rows = "\n".join(
        f'<figure><img src="beat_{b["i"]+1:02d}.png" alt="{b["title"]}">'
        f'<figcaption><b>{b["i"]+1:02d} · {b["tag"]}</b><span>{b["t0"]:.1f}–{b["t1"]:.1f}s</span>'
        f'<em>{b["title"]}</em></figcaption></figure>'
        for _, b in cells)
    alts = "\n".join(
        f'<li><b>{c["id"]}</b> {c["name"]} · 得分 {c["score"]} — {c["summary"]}</li>'
        for c in plan.get("alternatives", []))
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>故事板 · {plan['style_name']}</title>
<style>
 body{{margin:0;background:#0e1116;color:#eeede9;font-family:-apple-system,"PingFang SC",sans-serif}}
 .wrap{{max-width:1700px;margin:0 auto;padding:28px}}
 h1{{font-size:26px;margin:0 0 6px}} .meta{{color:#96a0ad;font-size:13px;margin-bottom:22px}}
 .grid{{display:flex;flex-wrap:wrap;gap:18px}}
 figure{{margin:0;width:250px}} img{{width:100%;border-radius:10px;border:1px solid #2a323d;display:block}}
 figcaption{{padding:8px 2px;font-size:12px;color:#96a0ad;display:flex;flex-direction:column;gap:3px}}
 figcaption b{{color:#8DE0C2}} figcaption em{{font-style:normal;color:#eeede9;font-size:14px}}
 .alt{{margin-top:26px;font-size:13px;color:#96a0ad}} .alt li{{margin:5px 0}}
</style></head><body><div class="wrap">
<h1>故事板 · {plan['style_name']}</h1>
<div class="meta">{plan['duration']:.1f}s · {len(plan['beats'])} 拍 · FPS {plan['fps']:g} ·
BGM {plan['bgm']['bpm']} BPM{'（开）' if plan['bgm']['on'] else '（关）'} ·
配色 {' '.join(plan['palette'].get(k,'') for k in ('a','b','c'))}</div>
<div class="grid">{rows}</div>
<div class="alt"><b>其他动效候选</b><ul>{alts}</ul></div>
</div></body></html>"""
    p = out_dir / "storyboard.html"
    p.write_text(html, encoding="utf-8")
    return p


# ── 方案文档 ─────────────────────────────────────────────────
def write_plan_md(plan: dict, job: Path) -> Path:
    L = [f"# 剪辑方案 · {plan['style_name']}（`{plan['style']}`）", "",
         f"- 时长 {plan['duration']:.2f}s · {plan['fps']:g}fps · "
         f"{plan['render']['width']}×{plan['render']['height']} @ {plan['render']['fps']}fps 输出",
         f"- 配色 a/b/c：`{plan['palette'].get('a')}` `{plan['palette'].get('b')}` `{plan['palette'].get('c')}`",
         f"- 品牌：{plan['brand']['name'] or '（未设）'}"
         + (f" · {plan['brand']['tagline']}" if plan['brand']['tagline'] else ""),
         f"- BGM：{'开' if plan['bgm']['on'] else '关'}，{plan['bgm']['bpm']} BPM（{plan['bgm']['mood']}）",
         f"- 封面大字（钩子）：**{plan['copy']['hook'] or '（未提取）'}**",
         f"- 主指标：**{plan['copy']['metric']['value']} {plan['copy']['metric']['unit']}**",
         "",
         "## 分镜", "",
         "| # | 时段 | 标签 | 标题 | 副标题 |", "|---|---|---|---|---|"]
    for b in plan["beats"]:
        L.append(f"| {b['i']+1} | {b['t0']:.2f}–{b['t1']:.2f}s | {b['tag']} | {b['title']} | {b['sub']} |")
    L += ["", "## 动效编排", ""]
    meta = motionlib.get(plan["style"]) or {}
    for m in meta.get("motion", []):
        L.append(f"- {m}")
    L += ["", "## 其他候选", ""]
    for c in plan.get("alternatives", []):
        L.append(f"- `{c['id']}` {c['name']}（得分 {c['score']}）：{c['summary']}")
    L += ["", "## 改法", "",
          "直接改 `plan.json` 再跑 `render.py`：换 `style` 换动效；改 `beats[].title` 改字幕；",
          "改 `palette` 换配色；`copy.hook` 是封面大字。", ""]
    p = job / "plan.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


# ── 主流程 ───────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="② 编排：出剪辑方案 + 故事板")
    ap.add_argument("--job", required=True)
    ap.add_argument("--style", default=None, help="动效 id（route/impact/editorial/dashboard/magazine）")
    ap.add_argument("--beats", type=int, default=0, help="强制节拍数")
    ap.add_argument("--brand-name", default="")
    ap.add_argument("--brand-tagline", default="")
    ap.add_argument("--brand-cta", default="")
    ap.add_argument("--palette", default="", help="覆盖配色 a,b,c")
    ap.add_argument("--hook", default="", help="手动指定封面大字")
    ap.add_argument("--nodes", default="", help="route 动效的节点标签")
    ap.add_argument("--bpm", type=int, default=0)
    ap.add_argument("--no-bgm", action="store_true")
    ap.add_argument("--no-storyboard", action="store_true")
    args = ap.parse_args()

    job = paths.job_dir(args.job)
    aj = job / "analysis.json"
    if not aj.exists():
        log(f"❌ 找不到 {aj}\n   先跑：python3 understand.py --input=你的视频 --job={args.job}")
        return 1
    a = json.loads(aj.read_text(encoding="utf-8"))

    plan = build_plan(a, args)
    (job / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    md = write_plan_md(plan, job)
    log(f"\n方案：{plan['style_name']}（{plan['style']}） · {len(plan['beats'])} 拍 · "
        f"BGM {plan['bgm']['bpm']}BPM · 钩子「{plan['copy']['hook']}」")
    log(f"  plan.json / {md.name} 已写")

    if args.no_storyboard:
        log("\n跳过故事板（--no-storyboard）")
    else:
        log("  渲染故事板（每拍一张代表帧）…")
        try:
            sp = storyboard(plan, job)
            if sp:
                log(f"  故事板 → {sp}")
                log(f"  可点开的版本 → {job/'previews'/'storyboard.html'}")
        except Exception as exc:  # noqa: BLE001
            log(f"  ⚠️ 故事板失败（不影响后续渲染）：{type(exc).__name__}: {str(exc)[:120]}")

    log(f"\n下一步（选定后出片）：python3 render.py --job={args.job}\n"
        f"想换风格：python3 plan.py --job={args.job} --style=impact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
