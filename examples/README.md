# 示例

`plan.example.json` 是一份可以直接拿来改的渲染配置：

```bash
# 1) 先看懂你的视频
python3 ../scripts/understand.py --input=你的口播.MOV --job=第一条

# 2) 生成一份真实的 plan.json
python3 ../scripts/plan.py --job=第一条

# 3) 把里面的 beats / palette / copy 换成你要的（可参考 plan.example.json 的字段说明）
#    然后出片
python3 ../scripts/render.py --job=第一条 --export=~/Downloads/交付
```

字段含义：

| 字段 | 说明 |
|---|---|
| `style` | 动效 id：`route` / `impact` / `editorial` / `dashboard` / `magazine` |
| `palette` | `a` 主色、`b` 浅色（正文）、`c` 强调色、`bg` 底色 |
| `face.guard_px` | 720×1280 上的"不压脸禁区" `[x, y, w, h]`；检测不准时可手动改大 |
| `beats[]` | 分镜：`t0/t1` 是时间（秒），`title` 上屏大字（**建议 ≤ 12 字**），`sub` 小字 |
| `copy.hook` | 封面大字 |
| `copy.metric` | `dashboard` 动效右侧那个大指标 |
| `route.nodes` | `route` 动效沿途节点标签（留空则只走光点，不显示文字） |
| `bgm` | `bpm` 与 `mood`（`warm` / `bright`），`on:false` 就是不要配乐 |
