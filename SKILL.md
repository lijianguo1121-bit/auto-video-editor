---
name: auto-video-editor
description: 口播短视频"看懂再剪"工作台。把一条口播视频丢进来，自动理解（本地转写、分句、抽帧、镜头切换、人脸安全区、静音与语速），出一份剪辑方案与故事板，选好动效后逐帧渲染成片并生成抖音封面。口播原声与口型 100% 保留，视频不出本机。触发词：自动剪辑、视频剪辑、口播剪辑、看懂视频、视频理解、转写、字幕、自动配乐、视频动效、动效模板、故事板、分镜、封面、抖音封面、剪一条视频、给视频加动效、auto-video-editor、video editor。
agent_created: true
---

# auto-video-editor · 看懂再剪

一句话：**把视频交进来，先读懂它，再用设计过的动效层剪出来。**

和其他"AI 剪辑"最大的区别有两条：

1. **它先看懂。** 转写、分句、语速、停顿、镜头切点、人在画面哪儿 —— 全部先量化，
   再谈怎么剪。方案是"有据可依"的，不是套模板。
2. **它不动你的原声。** 做法是「原片做底 + 网页动效层叠加」，逐帧抓屏直通管道合成，
   不存在 AI 换脸、换声、改口型。成片与原片的音频包络相关性正常 ≥ 0.93。

## 一条视频出什么

| 产物 | 说明 |
|---|---|
| `analysis.json` | 结构化事实：时长/画幅/帧率、转写分句、节拍、镜头切点、人脸安全区、静音与语速 |
| `brief.md` | 人类可读的理解简报（转写时间轴 + 节拍建议 + 钩子候选 + 动效候选） |
| `plan.json` | **渲染配置，纯数据、可直接手改**（分镜标题、配色、BGM、动效） |
| `plan.md` | 创作方案（分镜表 + 动效编排 + 改法） |
| `previews/storyboard.png` | 故事板总览：每一拍一张代表帧，先看再渲 |
| `previews/storyboard.html` | 可点开的故事板 |
| `out/NN_<style>.mp4` | 成片：720×1280 / 30fps / 原声保留 |
| `covers/cover_3x4.png` `cover_9x16.png` | 抖音封面（一行大字 + 一行小字 + 品牌标签） |

## 四步开始

```bash
cd <skill>/scripts
python3 doctor.py                                   # 1) 环境自检，缺什么它会说
python3 understand.py --input=某视频.MOV --job=我的任务   # 2) 看懂它
python3 plan.py --job=我的任务                        # 3) 出方案 + 故事板
python3 render.py --job=我的任务 --export=~/Downloads/交付  # 4) 出片
```

`<skill>` = `~/.workbuddy/skills/auto-video-editor`。
第 3 步出故事板后**先看一眼再渲**：渲一条 30 秒的片约 2–4 分钟，改 `plan.json` 比改片子便宜得多。

### agent 该怎么用它（重要）

脚本负责**事实与默认值**，创意判断交给 agent / 人。所以标准动作是：

1. 跑 `understand.py`，然后**读 `brief.md`**（转写可能有误听，尤其公司名、金额、行话）。
2. 把转写里的明显误听改掉（术语表 `assets/glossary.json` 可以沉淀自己的行话）。
3. 用 `plan.json` 做创意决策：把 ASR 直出的长句**改成能上屏的短句**（≤ 12 字最好）、
   挑钩子当封面大字、必要时换 `style`、改 `palette`。
4. 跑 `plan.py` 出故事板 → 给用户看 → 确认后 `render.py`。

> 默认生成的标题是"原文里信息量最高的连续片段"，能看但不够狠。
> **动手改 `plan.json` 的 `beats[].title` 是这套流程里最值钱的一步。**

## 20 个能力点，4 条命令

### ① understand —— 看懂

```bash
# 基础：本地转写（faster-whisper）+ 抽帧 + 人脸 + 节拍
python3 understand.py --input=视频.MOV --job=任务名

python3 understand.py --input=视频.MOV --job=任务名 --model=medium   # 更准，更慢
python3 understand.py --input=视频.MOV --job=任务名 --lang=auto      # 自动判语言
python3 understand.py --input=视频.MOV --job=任务名 --no-transcribe  # 只做画面/音频分析
python3 understand.py --input=视频.MOV --job=任务名 --samples=24     # 人脸抽帧数
```

它内部干这些事：`ffprobe（PyAV）→ 抽 16k 单声道音轨 → faster-whisper 转写（VAD + 词级时间戳）
→ 按「段落边界 → 标点 → 长度」切句 → 术语表纠错 → 帧差检测镜头切点 → 抽帧做 Haar 人脸检测
并出「不压脸禁区」→ 包络法算静音/语速 → DP 把句子切成 4–8 拍 → 给动效打分排序`。

### ② plan —— 编排

```bash
python3 plan.py --job=任务名
python3 plan.py --job=任务名 --style=impact        # 换动效（见下表）
python3 plan.py --job=任务名 --beats=6             # 强制 6 拍
python3 plan.py --job=任务名 --hook="封面大字" --nodes="深圳,成都,杭州"
python3 plan.py --job=任务名 --palette="#8DE0C2,#F5F2E9,#FF9B79"
python3 plan.py --job=任务名 --brand-name=IMAI --brand-tagline="AI 数字员工"
python3 plan.py --job=任务名 --no-bgm --no-storyboard
```

### ③ render —— 出片

```bash
python3 render.py --job=任务名
python3 render.py --job=任务名 --styles=route,impact,dashboard   # 一条素材多风格
python3 render.py --job=任务名 --max-seconds=8                  # 只渲前 8 秒，快速试片
python3 render.py --job=任务名 --fit=blur                       # 横屏素材加模糊底衬不裁画面
python3 render.py --job=任务名 --crf=17 --preset=slow           # 更高质量
python3 render.py --job=任务名 --export=~/Downloads/交付         # 拷到交付目录
```

### ④ cover —— 封面（也能单独重出）

```bash
python3 cover.py --job=任务名
python3 cover.py --job=任务名 --ratios=9x16 --big="3步搞定获客" --small="AI 替你干活"
```

## 动效库

| id | 名称 | 适合内容 | 视觉动作 | 冲击力 |
|---|---|---|---|---|
| `route` | 航线落地 | 招商 / 城市 / 增长 / 门店扩张 | 航线生长，节点按节拍依次点亮，涟漪扩散 | 4/5 |
| `impact` | 冲击大字 | 观点 / 反转 / 情绪 / 爆点 | 大字砸入，斜切色块错位擦入，光斑爆开 | 5/5 |
| `editorial` | 极简章节 | 知识口播 / 讲解 / 教程 | 细线划开，章节号淡入，字距收紧入场 | 2/5 |
| `dashboard` | 数据仪表盘 | 数据 / 业绩 / 成本 / 效率 | 网格淡入，柱状条生长，指标数字滚动 | 3/5 |
| `magazine` | 杂志编辑 | 人物 / 品牌故事 / 访谈 / 婚礼 | 刊头压入，衬线标题升起，描边框绘入 | 3/5 |

`plan.py` 会读转写文本、数字密度、语速，给这几套打分并排序（`analysis.json` 的
`recommend.candidates`）。想加一套：见 `references/motion-templates.md`。

## 关键设计（都是踩出来的）

1. **人脸安全区是算出来的，不是猜的。** 抽 16 帧做 Haar 检测，并成总包盒，外扩 8% 得到
   「不压脸禁区」。动效层再算上下两块可排版区域，**自动挑更宽的那一侧**放卡片。
   自拍构图（脸在下半屏）就把卡片放上方，反之放下方。卡片永远不越界。
2. **逐帧抓屏直通管道。** 每帧 PNG 从 Playwright 直接写进 ffmpeg 的 stdin，**不落中间帧文件**。
   一套 30s 的 720×1280 alpha 帧序列落盘就是 1GB+，落盘必然把磁盘打满
   （现象是浏览器莫名 `TargetClosedError`）。
3. **音频两步法响度归一。** 先 `loudnorm print_format=json` 量出 `input_i`，
   再把实测值回填给第二次 `loudnorm` + `alimiter` 兜底。单次归一不可靠。
4. **配乐自带侧链。** BGM 是按 BPM 用 numpy 合成的（无版权素材），并且**用口播音轨的包络
   把人声段落压低 70%** —— 说话时音乐自动退让，不用手调。
5. **中文标题按"语义块"折行。** 逐字折行会把"客服销售"拆成"客服销/售"。所以先把文字切成块
   （数字+单位 / 英文串 / 标点 / 汉字 2 字组），再按块装行、逐档缩字号。
6. **切句按"段落边界 → 标点 → 长度"。** 只按长度硬切会把标题断在半句话上
   （"2026年企业省钱最快的方法不是"）。VAD 段落边界天然落在换气处，是第一优先级；
   再给 whiser 一个"请补标点"的引导词。
7. **截图必须带 alpha。** `page.screenshot(omit_background=True)` + `body{background:transparent}`，
   否则动效层会把原片盖成全黑。
8. **无头浏览器不认 emoji**（渲染成豆腐块），模板里一律用纯文字。
9. **沙箱里别 `nohup … &` 跑长任务**，会被外层信号带走。用受管后台任务。
10. **工作区目录已存在时 `mkdir(exist_ok=True)` 仍可能报 EEXIST**（沙箱 broker 行为），
    所以建目录统一走 `paths.ensure_dir()`（先判断再建）。

## 产物在哪

```
~/AutoVideoEditor/
└── jobs/<任务名>/
    ├── analysis.json  brief.md  plan.json  plan.md
    ├── audio/voice.wav  audio/music.wav  audio/mix.m4a
    ├── frames/s_*.jpg              抽样帧（人脸 + 故事板）
    ├── previews/storyboard.png  previews/beat_*.png  previews/storyboard.html
    ├── work/base.mp4               规整后的底片（可删）
    ├── covers/firstframe.jpg  covers/cover_*.png
    └── out/NN_<style>.mp4          ✅ 成片
```

换工作区：`export AVE_WORKSPACE=/path/to/disk`。

## 输出规格

| 项 | 值 |
|---|---|
| 画面 | 720×1280 / 30fps / H.264（横屏原片自动加模糊底衬，不裁掉画面） |
| 音频 | AAC 192k / 48kHz / 立体声，口播原声为主轨 + 合成 BGM |
| 响度 | 目标 -15 LUFS、真峰值 -1.7 dBFS（两步法） |
| 质检 | 成片与原片做音频包络互相关，正常 ≥ 0.93；低于 0.9 说明原声被动了，要查 |

## 何时用 / 何时不用

| 场景 | 用不用 |
|---|---|
| 口播视频要加动效、字幕、配乐、封面 | ✅ 正解 |
| 一条素材批量出多个风格版本 | ✅ 正解（`--styles=a,b,c`） |
| 要先"看懂"视频内容再决定怎么剪 | ✅ 正解 |
| 要改变原片口播内容、换词、配音 | ❌ 这不是它的活 |
| 要按剪辑点拼接多个片段 | ❌ 它做"整片包装"，不做剪辑点 |

## 隐私

**默认全程本地。** 转写用本机 faster-whisper，画面理解用抽帧 + 帧差 + 人脸检测，
不调用任何云端模型，视频与音频不出本机。需要联网的只有第一次拉 Whisper 模型（约 460MB）。

## 排错

先跑 `python3 doctor.py`。仍然卡住看 `references/troubleshooting.md`，
架构与数据流看 `references/architecture.md`，加动效看 `references/motion-templates.md`。
