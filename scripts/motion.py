"""动效库索引与自动匹配。

每套动效 = `assets/motion.html` 里的一段 CSS 皮肤 + 一个 `draw(t)` 函数。
本模块只存**元数据**（给"按内容自动挑动效"用），绘制实现在 HTML 里。

加一套动效：① 在 motion.html 里写 `TPL['<id>']`；② 在这个 LIBRARY 里补一条。
"""
from __future__ import annotations

import argparse
import json

# 分组语义：authority 权威 / growth 增长 / impact 冲击 / editorial 编辑 / brand 品牌
LIBRARY: list[dict] = [
    {
        "id": "route",
        "name": "航线落地",
        "group": "growth",
        "summary": "一条航线生长出来，城市节点依次点亮，计数滚动收尾",
        "motion": ["航线 SVG 描边生长", "节点弹簧点亮 + 涟漪", "计数 0→N 滚动", "底部进度条走完"],
        "best_for": ["招商", "城市合伙人", "加盟", "门店扩张", "增长"],
        "keywords": ["城市", "合伙人", "加盟", "门店", "覆盖", "开放", "入驻", "落地", "城市", "全国"],
        "impact": 4,
        "palette": ["#102A3A", "#8DE0C2", "#F5F2E9", "#FF9B79"],
        "good_with_numbers": True,
    },
    {
        "id": "impact",
        "name": "冲击大字",
        "group": "impact",
        "summary": "关键词砸入画面，色块错位撕开，适合观点与反转",
        "motion": ["大字弹簧砸入 + 屏幕微震", "斜切色块错位擦入", "关键词描边强调", "收尾定版"],
        "best_for": ["观点", "反转", "高能", "情绪", "爆点"],
        "keywords": ["其实", "真相", "错了", "别", "千万", "记住", "颠覆", "醒醒", "骗"],
        "impact": 5,
        "palette": ["#0B0B0D", "#FF3B5C", "#FFE12F", "#F5F2E9"],
        "good_with_numbers": True,
    },
    {
        "id": "editorial",
        "name": "极简章节",
        "group": "editorial",
        "summary": "超大留白 + 细线划开 + 章节号，讲清楚一件事",
        "motion": ["细线划开（水平展开）", "章节号淡入", "标题字距收紧入场", "轻推镜"],
        "best_for": ["知识口播", "讲解", "教程", "拆解"],
        "keywords": ["第一", "第二", "第三", "步骤", "方法", "怎么", "如何", "拆解", "原因", "逻辑"],
        "impact": 2,
        "palette": ["#F7F5F0", "#1C1C1E", "#B9B2A4", "#8DE0C2"],
        "good_with_numbers": False,
    },
    {
        "id": "dashboard",
        "name": "数据仪表盘",
        "group": "authority",
        "summary": "网格上柱状条生长、数字滚动、指标卡逐张就位",
        "motion": ["柱状条从底部长出", "多指标数字滚动", "指标卡错开滑入", "网格线淡入"],
        "best_for": ["数据", "业绩", "复盘", "成本", "效率"],
        "keywords": ["成本", "效率", "增长", "下降", "提升", "百分比", "倍", "数据", "业绩", "ROI", "转化"],
        "impact": 3,
        "palette": ["#0F1720", "#8DE0C2", "#F5F2E9", "#FF9B79"],
        "good_with_numbers": True,
    },
    {
        "id": "magazine",
        "name": "杂志编辑",
        "group": "brand",
        "summary": "刊头压入、衬线大标题、图片框描边，人物与品牌故事",
        "motion": ["刊头压入（下拉定版）", "衬线标题逐行升起", "图片框描边绘入", "副标题淡显"],
        "best_for": ["人物", "品牌故事", "访谈", "婚礼"],
        "keywords": ["我", "故事", "年", "经历", "初心", "婚礼", "新人", "品牌", "团队"],
        "impact": 3,
        "palette": ["#1A1512", "#EF695B", "#F3D9B6", "#FFF9EF"],
        "good_with_numbers": False,
    },
]


def get(motion_id: str) -> dict | None:
    return next((m for m in LIBRARY if m["id"] == motion_id), None)


def rank(features: dict, top: int = 3) -> list[dict]:
    """按内容特征给动效库排序。

    features 可含：text（全文转写）、numbers（出现过的数字列表）、duration、
    speech_rate（字/秒）、orientation、has_face。
    """
    text = features.get("text") or ""
    numbers = features.get("numbers") or []
    duration = float(features.get("duration") or 0)
    rate = float(features.get("speech_rate") or 0)

    scored: list[tuple[float, dict]] = []
    for item in LIBRARY:
        score = 1.0 + item["impact"] * 0.10
        hits = [k for k in item["keywords"] if k in text]
        score += min(1.2, len(hits) * 0.28)
        if numbers and item["good_with_numbers"]:
            score += 0.35
        if item["id"] == "dashboard" and len(numbers) >= 3:
            score += 0.25
        if item["id"] == "impact" and rate >= 5.2:
            score += 0.22          # 语速快 → 冲击向更贴
        if item["id"] == "editorial" and rate and rate < 4.2:
            score += 0.22          # 语速慢 → 讲清楚向更贴
        if item["id"] == "route" and duration > 25:
            score += 0.12
        scored.append((score, {**item, "score": round(score, 3), "hits": hits}))

    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:top]]


def main() -> int:
    ap = argparse.ArgumentParser(description="动效库")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.json:
        print(json.dumps(LIBRARY, ensure_ascii=False, indent=2))
    else:
        print(f"\n动效库共 {len(LIBRARY)} 套：\n")
        for m in LIBRARY:
            print(f"  {m['id']:<10} {m['name']:<6} [{m['group']}] 冲击力 {m['impact']}/5")
            print(f"             {m['summary']}")
            print(f"             适合：{'、'.join(m['best_for'])}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
