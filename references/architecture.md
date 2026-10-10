# 架构与数据流

```
   视频 ──► understand.py ──► analysis.json ──► plan.py ──► plan.json ──► render.py ──► 成片
                                  │                            │                        │
                              brief.md                    previews/                covers/
                       （给人/agent 看）               （故事板，先看再渲）        （抖音封面）
```

四个脚本，单一职责，**只通过任务目录里的 JSON 交接**。所以任何一步都能单独重跑。

## 任务目录

```
jobs/<任务名>/
├── audio/voice.wav      understand 抽的 16k 单声道（转写 + 侧链用）
├── frames/s_*.jpg       understand 抽的帧（人脸检测，顺带可做故事板）
├── analysis.json        ← understand 的输出，后面所有步骤的唯一事实来源
├── brief.md             理解简报
├── plan.json            ← plan 的输出 / 也是人的输入（手改这个就能改片子）
├── previews/            ← plan 的输出（每拍代表帧 + 拼版 + 可点开的 HTML）
├── audio/music.wav      合成 BGM（render 生成，会复用）
├── audio/mix.m4a        混音 + 响度归一后的音轨
├── work/base.mp4        规整成 720×1280 的底片（可删）
└── out/NN_<style>.mp4   ✅ 成片
```

## 1. understand —— 把视频读成事实

```
probe(PyAV)                      时长/画幅/帧率/旋转/音轨
  └─ extract_audio(ffmpeg)       16k 单声道 wav
       ├─ transcribe(faster-whisper)  词级时间戳 + VAD + 标点引导词
       │    └─ split_sentences        段落边界 → 标点 → 长度
       │         └─ glossary          术语表纠错
       │              └─ score_sentence  钩子/数字/CTA/问句 打分
       ├─ audio_stats(numpy/wave)     RMS/峰值/停顿/有声占比
       └─ detect_scenes(PyAV 帧差)    镜头切点
  └─ face_pass(ffmpeg 抽帧 + Haar)   不压脸禁区（720×1280 像素）
       └─ group_beats(DP)            4–8 拍，边界落在换气处
            └─ recommend(motion.rank) 按内容给动效排序
```

**关键点**：分句的第一优先级是 VAD 段落边界。只按长度硬切会把标题断在半句话上
（"2026年企业省钱最快的方法不是"），这是最容易毁掉成片可读性的一环。

## 2. plan —— 出方案与故事板

- `build_plan()`：把 `analysis` 的节拍打磨成能上屏的短句（`smart_trim` 按语义块截取，
  不会把"客服销售"切成"客服销"）、挑主指标（跳过年份）、选动效、定配色与 BPM。
- `storyboard()`：对每一拍取"保持段"中间那一刻，用 Playwright 抓一张 720×1280，
  再拼成总览图 + 生成一个可点开的 HTML。
- `plan.json` 是**纯数据**。agent 或人改完直接 `render.py` 就行。

## 3. render —— 逐帧直通合成

```
build_base   原片 → scale/crop 或「模糊底衬 + 居中」→ 720×1280 底片（无音轨）
music.synth  numpy 合成 BGM（按 BPM；用口播包络做侧链，说话时压低 70%）
build_audio  原声 + BGM 混音 → 量 loudnorm → 回填实测值再归一 + alimiter
render_style Playwright 逐帧 render(t) → PNG 字节 → 直接写进 ffmpeg 的 stdin
             ffmpeg：base + 动效层 overlay → libx264
             再与 mix.m4a 合流（-c:v copy）
cover        截首帧（太黑自动后挪）→ cover.html → 3:4 / 9:16 截图
qa           音频包络互相关（原声是否被改动）+ 规格核对
```

**为什么直通管道**：一套 30 秒的 720×1280 alpha 帧序列落盘能到 1GB+。
落盘必然把磁盘打满，现象是浏览器莫名 `TargetClosedError`（看着像浏览器崩，其实是磁盘）。
`render_style()` 把每一帧 PNG 直接写进 ffmpeg stdin，峰值磁盘占用 ≈ 0。

## 4. 动效层（assets/motion.html）

一个**逐帧渲染页**，不是动画播放器：

- `render(t)` 完全由 `t` 决定，不读上一帧 → 可以任意顺序、任意并发抓帧，也便于分布式渲染。
- 版面先算后画：`computeLayout()` 按人脸禁区算出上下两块可排版区域，**挑更宽的那块**当安全带。
- 标题字号由安全带高度反推，并且**按语义块折行**（数字+单位 / 英文串 / 标点 / 汉字 2 字组）。
- 抓帧用 `omit_background=True`，页面背景透明 → 动效层不会盖住原片。

## 5. 音频链

```
voice.wav ─┐
           ├─ amix(normalize=0) ──► _mix.wav ──► loudnorm(量) ──► loudnorm(回填实测值)+alimiter ──► mix.m4a
music.wav ─┘                                     ↑
                                          -15 LUFS / -1.7 dBFS
```

单次 `loudnorm` 不可靠，必须两步：先 `print_format=json` 量，再回填
`measured_I / measured_TP / measured_LRA / measured_thresh / offset`。
选项名大小写敏感，`offset` 不叫 `measured_offset`。

## 6. 为什么不用 Remotion / HyperFrames 这类"HTML→视频"框架

它们的工作方式是**从零生成画面**，天然要重新生成人脸与声音 —— 和"口播原声 100% 保留"
直接冲突。本 skill 走的是「原片做底 + 动效层叠加」：原片音轨原样进成片，
画面只在上面叠一层，所以不存在换脸换声改口型。
