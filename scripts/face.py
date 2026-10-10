"""人脸检测（可"借壳"跑，支持批量，一次进程处理多帧）。

主流程只依赖 numpy，不硬塞 opencv：优先用进程内 `cv2`；没有就把整批帧交给
一个**带 cv2 的解释器**一次跑完（本机 `/usr/bin/python3` 带 cv2 4.13）。
都失败才退回肤色兜底，并明确标注结果不可靠。

    python3 face.py --json frame.jpg                 # 单帧
    python3 face.py --json-many a.jpg b.jpg c.jpg    # 一批，一次进程
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

FACE_SHRINK = 0.92          # Haar 的框比真脸大一圈，收紧后再并包盒
# 被"借壳"调起来的子进程必须**自己不许再借壳**，否则会无限套娃。
WORKER = os.environ.get("AVE_FACE_WORKER") == "1"
_BORROW_CACHE: list[list[str]] | None = None


# ── 进程内 cv2 ────────────────────────────────────────────────
def _cv2_boxes(images) -> list[list[list[int]]] | None:
    try:
        import cv2  # type: ignore
    except Exception:
        return None
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    out: list[list[list[int]]] = []
    for img in images:
        if img is None:
            out.append([])
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        boxes = cascade.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5,
                                         minSize=(60, 60))
        out.append([[int(x), int(y), int(w), int(h)] for (x, y, w, h) in boxes])
    return out


def _cv2_faces_many(paths: list[Path]) -> list[list[list[int]]] | None:
    try:
        import cv2  # type: ignore
    except Exception:
        return None
    return _cv2_boxes([cv2.imread(str(p)) for p in paths])


# ── 借壳：找一个带 cv2 的解释器 ────────────────────────────────
def _candidates() -> list[list[str]]:
    global _BORROW_CACHE
    if _BORROW_CACHE is not None:
        return _BORROW_CACHE
    cands: list[list[str]] = []
    env = os.environ.get("AVE_CV2_PYTHON")
    if env:
        cands.append([env])
    # 系统解释器常常自带 cv2（macOS 的 /usr/bin/python3 就有），优先试
    for p in ("/usr/bin/python3", "/usr/local/bin/python3", "/opt/homebrew/bin/python3"):
        if Path(p).exists():
            cands.append([p])
    for name in ("python3", "python"):
        p = shutil.which(name)
        if p and p not in [c[0] for c in cands]:
            cands.append([p])
    if sys.executable not in [c[0] for c in cands]:
        cands.append([sys.executable])
    _BORROW_CACHE = cands
    return cands


def _borrow_many(paths: list[Path]) -> list[list[list[int]]] | None:
    me = Path(__file__).resolve()
    env = {**os.environ, "AVE_FACE_WORKER": "1"}
    for cmd in _candidates():
        try:
            proc = subprocess.run(
                [*cmd, str(me), "--json-many", *[str(p) for p in paths]],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=600, env=env,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                continue
            data = json.loads(proc.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
            if data.get("method") == "opencv":
                return data["faces"]
        except Exception:
            continue
    return None


# ── 肤色兜底（不可靠，仅当没有任何 cv2 时用） ────────────────────
def _skin_boxes(path: Path) -> list[list[int]]:
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return []
    im = Image.open(path).convert("RGB")
    full_w, full_h = im.size
    small = im.copy()
    small.thumbnail((180, 320))
    a = np.asarray(small).astype("int16")
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mask = (r > 95) & (g > 40) & (b > 20) & (r > g) & (r > b) & ((r - np.minimum(g, b)) > 15)
    ys, xs = np.nonzero(mask)
    if len(xs) < 0.02 * a.shape[0] * a.shape[1]:
        return []
    sx, sy = full_w / small.width, full_h / small.height
    return [[int(xs.min() * sx), int(ys.min() * sy),
             int((xs.max() - xs.min()) * sx), int((ys.max() - ys.min()) * sy)]]


def detect_many(paths: list[str | Path]) -> dict:
    """一次判断一批帧。返回 {"faces": [[[x,y,w,h],...], ...], "method": str}"""
    paths = [Path(p) for p in paths]
    if not paths:
        return {"faces": [], "method": "none"}
    boxes = _cv2_faces_many(paths)
    if boxes is not None:
        return {"faces": boxes, "method": "opencv"}
    if WORKER:
        # 自己是被借壳起来的：没有 cv2 就干脆认输，别再套娃
        return {"faces": [[] for _ in paths], "method": "none"}
    boxes = _borrow_many(paths)
    if boxes is not None:
        return {"faces": boxes, "method": "opencv-borrowed"}
    return {"faces": [_skin_boxes(p) for p in paths], "method": "skin"}


def detect(path: str | Path) -> dict:
    r = detect_many([path])
    return {"faces": r["faces"][0] if r["faces"] else [], "method": r["method"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--json-many", action="store_true")
    args = ap.parse_args()
    if args.json_many:
        r = detect_many(args.images)
        print(json.dumps({"faces": r["faces"], "method": r["method"]}, ensure_ascii=False))
    elif args.json:
        print(json.dumps(detect(args.images[0]), ensure_ascii=False))
    else:
        print(json.dumps(detect(args.images[0]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
