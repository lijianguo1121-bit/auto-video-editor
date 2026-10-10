# 加一套动效（约 40 行）

动效 = **一段 CSS 皮肤 + 一个 `draw(t)` 函数**，都写在 `assets/motion.html` 里。
加完之后到 `scripts/motion.py` 的 `LIBRARY` 补一条元数据，它就能被"按内容自动匹配"选中。

## 1) 动效层的数据契约

渲染页拿到的配置（上游 `plan.py` 生成、`capture.py` 注入到 `window.__AVE`）：

```js
{
  style: 'route',            // 动效 id
  fps: 30, duration: 29.38,
  brand:  { name, tagline, cta },
  palette:{ a, b, c, bg },   // a=主色 b=浅色 c=强调色
  face:   { detected, guard_px:[x,y,w,h] },   // 720×1280 上的"不压脸禁区"
  hud:    { pill, progress },
  beats:  [ { i, t0, t1, tag, title, sub } ], // 分镜，t 以秒计
  copy:   { hook, metric:{value,unit} },
  route:  { nodes: [] },
  motion: { enter: 0.28, out: 0.16 }          // 进场/出场各占这一段的比例
}
```

## 2) 写皮肤

在 `<style>` 里加一节 `.style-<id>`：

```css
/* 06 · 你的动效 */
.style-myfx .card .tag{color:var(--a)}
.style-myfx .card .ttl{color:var(--b)}
.style-myfx .veil{position:absolute;inset:0;opacity:0;
  background:linear-gradient(90deg,color-mix(in srgb,var(--a) 40%,transparent),transparent)}
```

## 3) 写绘制函数

在 `const TPL = {}` 后面加：

```js
/* 06 · 你的动效：一句话说清它动什么 */
TPL.myfx = {
  build(){
    // 只在初始化时建 DOM，塞进 fx 容器
    const el = document.createElement('div'); el.className = 'veil';
    fx.appendChild(el); this.veil = el;
  },
  draw(t){
    const idx = beatIndexAt(t);            // 当前第几拍
    const b = BEATS[idx];
    const env = envelope(b, t);            // {p, enter, exit, vis, alpha}

    setCard(b, { maxSize: 56, ratio: 0.22, maxLines: 2, sub: true });
    place(env.alpha, (1 - env.enter) * 30 + env.exit * -20, 0.34);
    //                ↑ 透明度   ↑ 进场位移        ↑ 出场位移   ↑ 在安全带里的竖向位置(0~1)

    this.veil.style.opacity = (0.7 * env.vis).toFixed(3);
  }
};
```

可复用的工具（都在文件顶部）：`c01 / lin / easeOut / easeIn / easeIO / spring /
seeded / beatIndexAt / envelope / setCard / place / BAND / W / H`。

`BAND` 就是**自动挑出来的可排版安全带**：`{zone, top, bot, h}`。
自己的装饰元素也请落在 `BAND.top ~ BAND.bot` 之间，这样才不会压脸。

## 4) 登记元数据

`scripts/motion.py` 的 `LIBRARY` 里加一条：

```python
{
    "id": "myfx",
    "name": "我的动效",
    "group": "impact",                       # growth/impact/editorial/authority/brand
    "summary": "一句话说清它动什么",
    "motion": ["动作1", "动作2"],             # 会写进 plan.md
    "best_for": ["适合的内容类型"],
    "keywords": ["命中这些词的文案会优先选它"],
    "impact": 4,                             # 1-5，影响默认排序
    "palette": ["#0B0B0D", "#FF3B5C", "#FFE12F", "#F5F2E9"],  # [bg, a, b, c]
    "good_with_numbers": True,
},
```

## 5) 试

```bash
python3 plan.py --job=我的任务 --style=myfx        # 出故事板看每拍的样子
python3 render.py --job=我的任务 --styles=myfx --max-seconds=8   # 前 8 秒试片
```

## 硬约束（别踩）

1. **不许用 emoji**：无头浏览器渲染成豆腐块。
2. **不要外部请求**：图片、字体、CDN 一律自带（离线渲染）。
3. **`draw(t)` 必须无状态**：只能用 `t` 算，不能读上一帧的结果，否则逐帧抓取会飘。
4. **装饰别越界**：所有元素落在 `BAND` 内；`BAND` 是按人脸禁区算出来的。
5. **背景保持透明**：`html,body{background:transparent}`，抓帧用 `omit_background=True`，
   否则动效层会把原片盖黑。
6. **位置取偶**：`yuv420p` 色度 2×2 子采样，奇数尺寸/偏移会触发色度重采样、白降画质。
