# auto-video-editor · 看懂再剪

> 把一条口播视频丢进来，先**读懂它**，再用设计过的动效层剪出来 —— 原声一个字都不动。

一条命令看懂，三条命令出片：

```bash
python3 doctor.py                                        # 环境自检
python3 understand.py --input=我的口播.MOV --job=第一条   # 看懂：转写/分句/节拍/人脸安全区
python3 plan.py      --job=第一条                        # 出方案 + 故事板
python3 render.py    --job=第一条 --export=~/Downloads/交付 # 出片 + 封面
```

## 它和别的"AI 剪辑"不一样在哪

| | 常见的 AI 剪辑 | auto-video-editor |
|---|---|---|
| 怎么处理原片 | 用模型**重新生成**画面与声音 | **原片做底**，只往上叠动效层 |
| 口播原声 | 很容易被换掉 / 变调 | **100% 保留**（成片与原片音频包络相关性 ≥ 0.93） |
| 怎么决定节奏 | 套模板 / 按固定时长切 | 先**读懂**：转写分句、语速、停顿、镜头切点，再定拍子 |
| 人脸 | 常被字卡压住 | 逐帧人脸检测算"不压脸禁区"，卡片自动避让到更宽的一侧 |
| 素材隐私 | 常要上传到云端 | **全程本地**，视频不出本机 |
| 配乐 | 曲库（可能有版权问题） | 按 BPM 用 numpy 合成，**并用口播包络侧链退让** |

## 安装

需要 Python ≥ 3.9。

```bash
git clone https://github.com/lijianguo1121-bit/auto-video-editor.git ~/.workbuddy/skills/auto-video-editor
cd ~/.workbuddy/skills/auto-video-editor/scripts

python3 -m venv .venv && source .venv/bin/activate
pip install av faster-whisper numpy pillow playwright imageio-ffmpeg
playwright install chromium

python3 doctor.py       # 自检
```

`doctor.py` 会逐项检查并把缺的东西的安装命令直接打给你。

**不需要装系统 ffmpeg**：会自动用 `imageio-ffmpeg` 自带的静态二进制（含 libx264 / aac）。
**不需要 ffprobe**：媒体探测走 PyAV。

## 它到底"看懂"了什么

`understand.py` 全部本地跑，产出一份 `analysis.json`：

- **媒体**：时长 / 画幅 / 帧率 / 旋转 / 音轨规格（横竖屏自动判断）
- **转写**：faster-whisper（VAD + 词级时间戳），并给模型一个"请补标点"的引导词
- **分句**：按 **段落边界 → 标点 → 长度** 三级切句（只按长度硬切会把标题断在半句话上）
- **纠错**：术语表 `assets/glossary.json` 自动替换 ASR 误听（"素质员工"→"数字员工"）
- **音频**：RMS / 峰值 / 有声音占比 / 每一处停顿
- **画面**：帧差检测镜头切点
- **人脸**：抽帧 Haar 检测 → 总包盒 → 外扩 8% 的「不压脸禁区」（720×1280 像素坐标）
- **节拍**：DP 把句子切成 4–8 拍，边界落在说话人的换气处
- **建议**：语速 → BGM BPM；关键词命中 → 动效库排序

## 动效库（5 套，开箱可用）

| id | 名称 | 适合 | 动作 |
|---|---|---|---|
| `route` | 航线落地 | 招商 / 城市 / 增长 | 航线生长，节点按节拍点亮，涟漪扩散 |
| `impact` | 冲击大字 | 观点 / 反转 / 爆点 | 大字砸入，斜切色块错位擦入 |
| `editorial` | 极简章节 | 知识口播 / 教程 | 细线划开，章节号，字距收紧入场 |
| `dashboard` | 数据仪表盘 | 数据 / 业绩 / 成本 | 柱状条生长，指标数字滚动 |
| `magazine` | 杂志编辑 | 人物 / 品牌故事 | 刊头压入，衬线标题，描边框绘入 |

动效层是 `assets/motion.html` 里的一个逐帧渲染页：`render(t)` 只由 `t` 决定，
不依赖上一帧，所以可以精确逐帧抓取。加一套动效大约 40 行：见
[`references/motion-templates.md`](references/motion-templates.md)。

## 交付结构

```
~/AutoVideoEditor/jobs/<任务名>/
├── analysis.json          结构化事实
├── brief.md               理解简报（转写时间轴 / 节拍 / 钩子 / 动效候选）
├── plan.json              ★ 渲染配置，纯数据，手改它就能改片子
├── plan.md                创作方案
├── previews/storyboard.png 故事板：每拍一张代表帧
├── covers/cover_3x4.png    抖音封面
└── out/01_route.mp4        ✅ 成片
```

换工作区（比如挂到外置盘）：`export AVE_WORKSPACE=/Volumes/xxx/AutoVideoEditor`

## 常用命令

```bash
# 一条素材出多个风格
python3 render.py --job=第一条 --styles=route,impact,dashboard

# 只渲前 8 秒，先看对不对
python3 render.py --job=第一条 --max-seconds=8

# 横屏素材：加模糊底衬，不裁掉画面
python3 render.py --job=第一条 --fit=blur

# 换动效 / 换配色 / 换封面大字
python3 plan.py --job=第一条 --style=impact --palette="#FFE12F,#FFFFFF,#FF3B5C"
python3 cover.py --job=第一条 --big="3步搞定获客" --small="AI 替你干活"

# 更准的转写（更慢）
python3 understand.py --input=我的口播.MOV --job=第二条 --model=medium
```

## 输出规格

| 项 | 值 |
|---|---|
| 画面 | 720×1280 / 30fps / H.264 |
| 音频 | AAC 192k / 48kHz / 立体声；口播原声为主轨 + 合成 BGM |
| 响度 | -15 LUFS / 真峰值 -1.7 dBFS（先量后补的两步法） |
| 质检 | 成片与原片音频包络互相关 ≥ 0.93 判定"原声未被改动" |

## 为什么它是这么实现的（几个关键取舍）

- **逐帧抓屏直通管道合成**，不落中间帧：一套 30 秒的 720×1280 alpha 帧序列落盘就是 1GB+，
  落盘必然把磁盘打满（现象是浏览器莫名崩溃）。
- **人脸安全区是算出来的**，不是让模型"注意别挡脸"：抽帧检测 → 并包盒 → 外扩 → 上下两块可排版
  区域里挑更宽的一侧。
- **配乐侧链**：BGM 用口播轨的包络压低 70%，说话时音乐自动退让。
- **中文按语义块折行**：逐字折行会把"客服销售"拆成"客服销/售"。

更多踩坑记录见 [`references/troubleshooting.md`](references/troubleshooting.md)。

## 许可

MIT © 2026 OPC-AID
