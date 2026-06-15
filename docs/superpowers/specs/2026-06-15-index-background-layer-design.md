# index.html 背景层重构设计

日期：2026-06-15
状态：方案 A 已由用户确认，等待实现

## 背景

`index.html` 当前需要解决 macOS / Safari / Chromium 类浏览器在页面滚动到极限时的弹性滚动露底问题。之前将背景色或渐变分别补到 `html` 和 `body` 后，仍会在弹性区域看到偏黑的底层，而不是页面主体的渐变氛围。

根因判断：背景仍依赖文档流里的 `body` 绘制，浏览器弹性滚动露出的区域不一定按页面内容层继续绘制。仅检查 computed style 会误判，因为样式存在不代表弹性区域实际像素符合预期。

## 目标

- 弹性滚动露出的区域不出现白底或纯黑底。
- 背景视觉与页面主体一致，保持现有深蓝夜色、青色和琥珀色微光氛围。
- 背景层级更清晰：根画布负责兜底，固定背景层负责视觉，内容层只负责布局。
- 不改页面信息架构、卡片布局、链接、图片加载逻辑或 viewer 行为。

## 设计选择

采用方案 A：固定根背景层。

把页面背景从 `body` 内容容器中抽离，改为 viewport 级固定背景系统：

- `html` 保留深蓝兜底色，覆盖任何浏览器默认画布。
- `body` 作为透明内容容器，不再设置实色背景。
- `body::before` 固定铺满视口，承载主渐变背景。
- `body::after` 固定铺满视口，承载远处柔光层。
- `html::after` 保留现有噪点质感层。
- 内容容器继续使用现有 `z-index: 1`，确保卡片和 README 面板位于背景之上。

这个结构避免背景被文档高度和 `body` 边界裁切，也避免弹性滚动时浏览器只拿到 `body` 的纯色兜底。

## 具体实现

### 1. 背景变量

保留并集中定义 `--page-background`，作为主渐变资产：

- 左上琥珀径向光
- 右上青色径向光
- 底部偏蓝径向光
- 深蓝线性渐变底

`--page-background` 只用于固定背景层，不再同时直接铺在 `html` 和 `body` 上。

### 2. 根元素与 body

`html`：

- 设置 `min-height: 100%`
- 设置 `background-color: var(--bg-void)`

`body`：

- 保持 `min-height: 100vh`
- 设置 `background: transparent`
- 保留现有布局、字体、颜色、横向溢出隐藏

### 3. 固定背景层

`body::before`：

- `position: fixed`
- `inset: 0`
- `background: var(--page-background)`
- `background-attachment: fixed`
- `z-index: -3`
- `pointer-events: none`

`body::after`：

- 继续使用现有柔光径向渐变
- 改为 `inset: 0` 或略微外扩，避免边缘裁切
- `z-index: -2`
- `pointer-events: none`

如需保留现有网格层，应从 `body::before` 移到独立层，或合并进 `html::after` 的视觉层。不能让主背景层和网格层争用同一个伪元素。

### 4. 噪点与网格

现有 `html::after` 噪点层保留，但需要确认其 `z-index` 不遮挡交互：

- `position: fixed`
- `pointer-events: none`
- 位于内容层之上或背景层之上都可以，但不应产生明显遮罩

如果需要同时保留网格和噪点，优先将网格合并进一个固定装饰层，避免额外 DOM。

## 验收标准

- 页面正常滚动区域保持现有视觉氛围。
- 弹性滚动到顶部或底部时，露出的区域不是白色，也不是纯黑块。
- 浏览器实际截图的边缘区域能看到深蓝渐变或柔和色彩过渡。
- `node --test tests/*.test.mjs` 全部通过。
- `git diff --check` 通过。
- 增加或更新一个测试，防止 `body` 再次恢复为纯色背景层。

## 非目标

- 不重做 README 面板、卡片、瀑布流布局。
- 不调整图片数据、加载状态或点击逻辑。
- 不引入构建工具、CSS 预处理器或外部前端依赖。
- 不通过禁用滚动手感来掩盖问题。

## 风险与验证

弹性滚动的真实效果不能只靠 computed style 判断。实现完成后需要用实际浏览器截图或像素采样验证边缘区域，确认它不是单一纯黑背景。

Safari 的 rubber-band 细节可能与 Chromium 不完全一致，因此实现应依赖更稳的 viewport 固定背景层，而不是浏览器对 `html/body` 背景传播的具体行为。
