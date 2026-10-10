"""环境自检：一口气告诉你缺什么、怎么补。

    python3 doctor.py            # 体检
    python3 doctor.py --fix      # 只提示可自动补的（不会真装，避免污染环境）
"""
from __future__ import annotations

import argparse
import importlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ffmpeg_bin  # noqa: E402
import paths  # noqa: E402

OK, WARN, BAD = "✅", "⚠️ ", "❌"

results: list[tuple[str, str, str]] = []


def check(name: str, state: str, detail: str = "", hint: str = ""):
    results.append((state, name, detail or hint))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="打印可执行的修复命令")
    args = ap.parse_args()

    print("\n── auto-video-editor 环境自检 ──\n")

    # 1. Python
    v = sys.version_info
    check("Python", OK if v >= (3, 9) else BAD,
          f"{v.major}.{v.minor}.{v.micro} ({platform.machine()})",
          "需要 Python >= 3.9")

    # 2. 依赖模块
    mods = {
        "av": ("PyAV（媒体探测/抽帧）", "pip install av"),
        "faster_whisper": ("faster-whisper（本地转写）", "pip install faster-whisper"),
        "numpy": ("numpy", "pip install numpy"),
        "PIL": ("Pillow（故事板拼版）", "pip install pillow"),
        "playwright": ("Playwright（逐帧渲染）", "pip install playwright"),
    }
    missing = []
    for mod, (label, fix) in mods.items():
        try:
            importlib.import_module(mod)
            check(label, OK, "已安装")
        except Exception as exc:  # noqa: BLE001
            missing.append(fix)
            check(label, BAD, str(exc)[:60], fix)

    # 3. ffmpeg
    try:
        exe = ffmpeg_bin.ffmpeg()
        check("ffmpeg", OK, exe)
        for enc in ("libx264", "aac"):
            check(f"  编码器 {enc}", OK if ffmpeg_bin.has_encoder(enc) else BAD,
                  "可用" if ffmpeg_bin.has_encoder(enc) else "缺失")
        proc = subprocess.run([exe, "-hide_banner", "-filters"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        filters = proc.stdout.decode("utf-8", "replace")
        for flt in ("loudnorm", "alimiter", "overlay"):
            check(f"  滤镜 {flt}", OK if flt in filters else BAD,
                  "可用" if flt in filters else "缺失")
    except Exception as exc:  # noqa: BLE001
        check("ffmpeg", BAD, str(exc)[:80], "pip install imageio-ffmpeg")

    # 4. Playwright 浏览器
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    has_chromium = cache.exists() and any(p.name.startswith("chromium") for p in cache.iterdir())
    check("Chromium（无头渲染）", OK if has_chromium else BAD,
          str(cache) if has_chromium else "未安装浏览器内核",
          "playwright install chromium")

    # 5. 转写模型
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    models = sorted(p.name for p in hub.glob("models--*faster-whisper*")) if hub.exists() else []
    if models:
        check("Whisper 模型缓存", OK, ", ".join(m.replace("models--", "").replace("--", "/") for m in models))
    else:
        check("Whisper 模型缓存", WARN, "本地没有模型，首次转写会联网下载",
              "首次运行 understand.py 会拉 Systran/faster-whisper-small（约 460MB）")

    # 6. 中文字体（无头浏览器渲染中文必需，否则全是方框）
    font_hits = []
    for cand in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]:
        if Path(cand).exists():
            font_hits.append(Path(cand).name)
    check("中文字体", OK if font_hits else BAD,
          ", ".join(font_hits) if font_hits else "没找到中文字体，成片中文会变方框",
          "Linux 上装：sudo apt install fonts-noto-cjk")

    # 7. 工作区可写 + 磁盘
    ws = paths.workspace()
    try:
        paths.ensure_dir(ws)
        probe_file = ws / ".ave_write_test"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
        check("工作区可写", OK, str(ws))
    except Exception as exc:  # noqa: BLE001
        check("工作区可写", BAD, str(exc)[:70], "export AVE_WORKSPACE=/path/to/disk")

    try:
        st = os.statvfs(str(ws if ws.exists() else Path.home()))
        free_gb = st.f_bavail * st.f_frsize / 1024 ** 3
        check("磁盘余量", OK if free_gb > 3 else WARN,
              f"{free_gb:.1f} GB 可用",
              "低于 3GB 时逐帧渲染可能中断；本 skill 走管道合成，不落中间帧")
    except Exception:  # noqa: BLE001
        pass

    width = max(len(n) for _, n, _ in results) + 2
    bad = 0
    for state, name, detail in results:
        if state == BAD:
            bad += 1
        print(f"  {state} {name.ljust(width)} {detail}")

    print()
    if args.fix and missing:
        print("补依赖：")
        for cmd in missing:
            print(f"  {sys.executable} -m {cmd}")
        print()

    if bad:
        print(f"有 {bad} 项不达标，先补齐再跑。\n")
        return 1
    print("环境就绪，可以开跑：python3 understand.py --input=你的视频.mp4\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
