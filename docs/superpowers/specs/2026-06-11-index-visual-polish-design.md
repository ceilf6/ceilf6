# index.html 视觉精修设计（深蓝夜色方向）

日期：2026-06-11
状态：已与用户确认方向（深蓝夜色精修，排布不变）

## 目标

在**完全保留现有排布与交互**（顶部 README 玻璃面板 + 三张外链卡片 + 提示语 SVG + 下方三列 JS 瀑布流 + 点击打开 viewer.html）的前提下，对 index.html 做纯视觉层面的精修，提升质感与一致性。

## 约束

- HTML 结构零改动；唯一允许的例外是为瀑布流卡片设置内联 `--i` 自定义属性（由现有 JS 创建卡片时顺带设置）。
- 不改 viewer.html、images.js 的接口与行为；`openViewer(i)`、resize 逻辑保持原样。
- 不引入构建步骤或外部 JS 依赖；仅 CSS 与现有内联脚本的小改动。
- 三张外链卡片为 tokyonight 暗色系（#1a1b27），整体配色须与其协调（维持深蓝基调即原因之一）。

## 设计内容

### 1. 背景氛围（克制化）

- `body::after` 漂浮光斑：缩小径向渐变尺寸、不透明度整体下调（约降至现值的 60%）、动画周期放慢（22s → 30s 左右），观感从"彩色色块"变为"远处微光"。
- `body::before` 网格：线宽保持 1px 但颜色更淡；新增 `mask-image: radial-gradient(...)` 使网格中央可见、四周渐隐。
- 新增一层固定定位的极淡 SVG 噪点（data URI，`feTurbulence`），`mix-blend-mode: overlay`、低不透明度，消除大面积渐变的塑料感。

### 2. 字体与标题

- 字体加载：在现有 Azeret Mono + ZCOOL XiaoWei 基础上补充 Noto Sans SC（400/500/700），body 字体栈调整为中文优先走 Noto Sans SC。
- h1 保留 ZCOOL XiaoWei；增大字距（letter-spacing ≈ 0.06em）；`.accent`（ceilf6）由纯琥珀色改为琥珀→青的 `background-clip: text` 渐变。

### 3. README 玻璃面板

- 渐变描边（`.readme-section::before`）：保留双色渐变但宽度仍 1px、整体不透明度下调，更含蓄。
- 阴影减淡；内边距节奏微调。
- 三张卡片：圆角统一为 12px；悬停统一为"上浮 4px + 1px 青色细描边 + 阴影加深"，过渡曲线统一。

### 4. 瀑布流卡片

- 圆角 20px → 14px（内图 18px → 12px）。
- 阴影改为双层：近距离 1–2px 实影 + 远距离大半径虚影；悬停时细青色描边 + 上浮 6px。
- 取消悬停时 `img scale(1.05)`（晃动感），改为仅 `filter` 轻微提亮饱和。
- 扫光 `::before` 高光带不透明度减半。
- **修复 1**：入场延迟 nth-child 只写到第 11 个，而 images.js 有 15 张图；删除 nth-child 列表，JS 创建卡片时设置 `card.style.setProperty("--i", i)`，CSS 用 `animation-delay: calc(var(--i) * 60ms)`。
- **修复 2**：`cardIn` 动画 `forwards` 锁死 transform 导致悬停 `translateY` 失效；keyframes 改用独立的 `translate` 属性做入场位移，`transform` 留给悬停。

### 5. 收尾细节

- 自定义 WebKit 滚动条（深底、半透明亮色滑块）。
- `::selection`：青底深字。
- `@media (prefers-reduced-motion: reduce)`：关闭动画与过渡。
- 卡片与链接的 `:focus-visible` 青色描边。

## 不做的事

- 不改页面信息架构、文案、链接。
- 不改瀑布流算法与断点行为（900px / 640px 两档保持）。
- 不替换三张外链卡片的主题。

## 验收

- 排布与原版逐像素级一致（间距/圆角等微调除外），无元素增删。
- 15 张卡片全部有错峰入场。
- 卡片入场动画结束后悬停上浮生效。
- 移动端两档断点表现与原版一致。
