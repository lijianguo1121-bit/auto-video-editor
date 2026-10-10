"""封面生成（抖音版式：一行大字 + 一行小字 + 品牌小标签）。

    python3 cover.py --job=demo1 [--ratios=3x4,9x16] [--big="..."] [--small="..."]

底图默认取成片首帧（黑帧会自动往后挪）。想更炸的底图，可以把
`covers/firstframe.jpg` 丢给生图模型重画（保留人物不变形），再重跑本脚本。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ffmpeg_bin as ff  # noqa: E402
import paths  # noqa: E402

SIZES = {"3x4": (1080, 1440), "9x16": (1080, 1920)}


def first_frame(video: Path, out: Path) -> Path:
    """挑一张干净的底图。

    **优先用"底片"（不含动效层）当底图** —— 否则封面上会叠着动效层的品牌胶囊。
    再从几个候选时刻里挑曝中最合适的一张（太黑往后挪，太亮再往前找）。
    传入的 video 若是成片且同目录有 work/base.mp4，会自动改用底片。
    """
    from PIL import Image

    src = video
    base = video.parent.parent / "work" / "base.mp4"
    if base.exists():
        src = base

    best: tuple[float, Path] | None = None
    for t in (0.4, 1.2, 2.0, 3.2, 5.0):
        cand = out.with_name(f"_cand_{t}.jpg")
        ff.ff("-y", "-ss", f"{t}", "-i", str(src), "-frames:v", "1", "-q:v", "2", str(cand))
        if not cand.exists():
            continue
        im = Image.open(cand).convert("L")
        mean = im.resize((1, 1)).getpixel((0, 0))      # 整图平均亮度
        score = -abs(mean - 118)          # 118 左右是舒服的中曝光
        if best is None or score > best[0]:
            best = (score, cand)
    if best is None:
        raise RuntimeError(f"截不到底图：{src}")
    best[1].replace(out)
    for f in out.parent.glob("_cand_*.jpg"):
        try:
            f.unlink()
        except Exception:
            pass
    return out


def make_covers(job: Path, plan: dict, video: Path,
                sizes: tuple[str, ...] = ("3x4", "9x16"),
                big: str = "", small: str = "") -> list[Path]:
    from playwright.sync_api import sync_playwright

    from capture import LAUNCH_ARGS

    cov = paths.ensure_dir(job / "covers")
    first = first_frame(Path(video), cov / "firstframe.jpg")

    brand = plan.get("brand", {}) or {}
    hook = big or (plan.get("copy", {}) or {}).get("hook") or ""
    beats = plan.get("beats", []) or []
    if not hook and beats:
        hook = beats[-1].get("title", "")
    sub = small or brand.get("cta") or brand.get("tagline") or \
        (beats[-1].get("title", "") if beats else "")
    if sub == hook:
        sub = ""
    pal = plan.get("palette", {}) or {}

    out: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=LAUNCH_ARGS)
        for name in sizes:
            if name not in SIZES:
                continue
            w, h = SIZES[name]
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            cfg = {
                "w": w, "h": h, "live": True, "photo": paths.as_uri(first),
                "a": pal.get("a", "#8DE0C2"), "b": pal.get("b", "#F5F2E9"),
                "c": pal.get("c", "#FF9B79"),
                "kicker": (brand.get("name", "") + (" · " + brand["tagline"] if brand.get("tagline") else "")).strip(" ·"),
                "big": hook or "封面大字",
                "small": sub,
                "foot": brand.get("tagline", ""),
                "bigMax": 3 if name == "9x16" else 4,
            }
            page.add_init_script("window.__AVE = " + json.dumps(cfg, ensure_ascii=False) + ";")
            page.goto(paths.as_uri(paths.ASSETS_DIR / "cover.html"), wait_until="load")
            try:
                page.wait_for_function("() => window.__ready === true", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(220)
            f = cov / f"cover_{name}.png"
            page.screenshot(path=str(f))
            out.append(f)
            page.close()
        browser.close()
    (cov / "cover.json").write_text(
        json.dumps({"hook": hook, "sub": sub, "brand": brand}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="封面生成")
    ap.add_argument("--job", required=True)
    ap.add_argument("--video", default="", help="底片来源，默认取 out/ 里第一条成片")
    ap.add_argument("--ratios", default="3x4,9x16")
    ap.add_argument("--big", default="")
    ap.add_argument("--small", default="")
    args = ap.parse_args()

    job = paths.job_dir(args.job)
    plan = json.loads((job / "plan.json").read_text(encoding="utf-8"))
    if args.video:
        video = Path(args.video).expanduser()
    else:
        outs = sorted((job / "out").glob("*.mp4"))
        if not outs:
            print(f"❌ out/ 里没有成片，先跑 render.py")
            return 1
        video = outs[0]
    files = make_covers(job, plan, video,
                        tuple(s.strip() for s in args.ratios.split(",") if s.strip()),
                        args.big, args.small)
    print("封面：")
    for f in files:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
