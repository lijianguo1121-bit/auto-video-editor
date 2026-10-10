"""动效层抓帧器（Playwright 同步 API）。

用法：
    from capture import MotionStage
    st = MotionStage(cfg)
    png = st.frame(1.25)          # 单帧 PNG 字节（带 alpha）
    st.close()

之所以不落中间帧文件：一整套 720×1280 的 alpha 帧序列能到 GB 级，
本机磁盘常年只剩几个 GB。所以 render.py 拿到字节**直接喂给 ffmpeg 的 stdin**。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths  # noqa: E402

MOTION_HTML = paths.ASSETS_DIR / "motion.html"

LAUNCH_ARGS = [
    "--force-color-profile=srgb",
    "--disable-lcd-text",
    "--font-render-hinting=none",
    "--disable-dev-shm-usage",
]


class MotionStage:
    def __init__(self, cfg: dict, width: int = 720, height: int = 1280, timeout_ms: int = 60000):
        from playwright.sync_api import sync_playwright

        self.cfg = cfg
        self.width, self.height = width, height
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(args=LAUNCH_ARGS)
        self.page = self.browser.new_page(
            viewport={"width": width, "height": height}, device_scale_factor=1)
        self.page.set_default_timeout(timeout_ms)
        self.page.add_init_script("window.__AVE = " + json.dumps(cfg, ensure_ascii=False) + ";")
        url = paths.as_uri(MOTION_HTML) + "?style=" + str(cfg.get("style", "route"))
        self.page.goto(url, wait_until="load")
        self.page.wait_for_function("() => typeof window.render === 'function'")
        # 等字体就位，避免首帧字体回退
        try:
            self.page.wait_for_function("() => document.fonts && document.fonts.status === 'loaded'",
                                        timeout=8000)
        except Exception:
            pass

    def frame(self, t: float) -> bytes:
        self.page.evaluate("t => window.render(t)", float(t))
        return self.page.screenshot(type="png", omit_background=True)

    def close(self) -> None:
        try:
            self.browser.close()
        finally:
            self._pw.stop()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
