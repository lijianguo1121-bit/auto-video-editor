# 排错

先跑 `python3 doctor.py`，它会逐项告诉缺什么、怎么补。

## 转写

| 症状 | 原因 / 解法 |
|---|---|
| 第一次跑很慢，卡在"加载模型" | 在拉 `Systran/faster-whisper-small`（约 460MB）。之后就本地了 |
| 全篇没有标点，标题被切在半句话上 | 已经内置"请补标点"的引导词 + 按 VAD 段落边界切句。仍不行就换 `--model=medium` |
| 专业词老是听错 | 往 `assets/glossary.json` 加词条（"素质员工"→"数字员工" 这种） |
| 转写很慢（CPU） | 30 秒素材约 20–40 秒。想快用 `--model=base`；想准用 `--model=medium`（约 1.5GB） |
| 无音轨 | 会提示"没有音轨"并退回按时长均分节拍；字幕会空 |

## 人脸 / 排版

| 症状 | 原因 / 解法 |
|---|---|
| 日志写"人脸：未检出" | 没有 cv2 就退回肤色兜底，结果不可靠。装 `opencv-python`，或用 `AVE_CV2_PYTHON=/usr/bin/python3` 指一个带 cv2 的解释器"借壳" |
| 卡片压到脸了 | 看 `brief.md` 里的"不压脸禁区"是不是明显偏小（检测漏了）。可以手动改 `plan.json` 的 `face.guard_px` 放大禁区 |
| 卡片位置怪 / 空间太窄 | 卡片会挑上下更宽的一侧。人脸占了下半屏时卡片在上方，属正常 |
| 中文变成方框 | 缺中文字体。macOS 自带 PingFang/STHeiti；Linux `sudo apt install fonts-noto-cjk` |

## 渲染

| 症状 | 原因 / 解法 |
|---|---|
| `TargetClosedError`，浏览器崩了 | 99% 是磁盘满了。本 skill 走管道合成不落中间帧；如果是自己改了代码落盘，检查磁盘 |
| 逐帧很慢 | 30 秒素材约 2–4 分钟/风格（881 帧）。试片用 `--max-seconds=8`；`--fps=24` 也能快一点 |
| 成片没有音轨 | 原片本来就没音轨，或 `plan.json` 的 `duration` 和实际不符导致 `-t` 截空 |
| 原声保留相关性 < 0.93 | 说明原声被动过。检查是否误加了变速/变调滤镜 |
| `mkdir ... EEXIST` | 沙箱 broker 下目标目录已存在仍会报错。统一走 `paths.ensure_dir()`；重跑同一任务名先删 `jobs/<任务名>` |

## 音频

| 症状 | 原因 / 解法 |
|---|---|
| `Option not found: measured_target_offset` | loudnorm 的选项名大小写敏感：应是 `measured_I / measured_TP / measured_LRA / measured_thresh / offset` |
| 成片忽大忽小 | 单次 loudnorm 不稳，必须两步法：先 `print_format=json` 量，再回填实测值 |
| 音乐盖住人声 | 调 `plan.json` 里 BGM 强度，或确认 `audio/voice.wav` 存在（侧链要用它） |
| 不想要 BGM | `render.py --no-bgm`，或 `plan.json` 里 `"bgm":{"on":false}` |

## 环境

| 症状 | 原因 / 解法 |
|---|---|
| `找不到 ffmpeg` | `pip install imageio-ffmpeg`，或设 `AVE_FFMPEG=/path/to/ffmpeg` |
| 没有 ffprobe | 正常，本 skill 不用 ffprobe，媒体探测走 PyAV |
| 沙箱里长任务被杀 | 别用 `nohup … &`，用受管后台任务；前台跑到超时会自动转后台，不会杀 |
| 磁盘紧张 | 产物里的 `work/base.mp4` 可随时删；`render.py` 会自动清理中间文件 |
