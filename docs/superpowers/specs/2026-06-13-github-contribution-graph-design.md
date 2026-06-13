# GitHub Contribution Graph Design

## 背景

README 当前是个人主页结构：顶部三张卡片展示 GitHub Stats、Blog、Vlog，随后是个人简介、项目探索、社区贡献和荣誉。现有本地 SVG 卡片使用统一的 Tokyo Night 风格：

- 深色背景：`#1a1b27`
- 标题蓝：`#70a5fd`
- 数据青：`#38bdae`
- 强调紫：`#bf91f3`
- 卡片圆角：`5px`
- 字体：`'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif`

目标是在 README 中新增 GitHub 贡献图，并让它看起来像当前视觉体系的一部分，而不是外部服务拼贴。

## 已确认决策

### 位置

贡献图放在顶部三张卡片和简介之后，`我的一些探索` 标题之前。

这个位置让贡献图成为顶部个人主页门面的延展：先展示身份和入口，再展示持续编码活跃度，最后进入具体项目列表。

### 生成方式

不直接引用第三方动态图片服务。新增本仓库自生成 SVG 链路：

- 生成文件：`assets/github-contribution-graph.svg`
- README 使用本地图片引用
- 图片由 GitHub Actions 定时生成并提交

这样可以避免第三方服务不可用、样式不可控、参数变更等问题。

### 图像形态

使用宽幅年度热力图，而不是压缩成 `340x200` 统计卡：

- 建议 SVG 尺寸约 `1020x184`，对应顶部三张 `340x200` 卡片的合计宽度，并为标题行和 7 行贡献格保留空间
- README 中居中展示，宽度使用 `99%`，对齐顶部三张 `33%` 卡片
- 保留年度贡献格子的可读性，并在格子内显示每日具体贡献数
- 展示 `GitHub Contribution Graph` 标题和 `active ... days` 活跃天数
- 不展示贡献总数、用户名、时间范围、更新时间、月份、星期或图例

### 视觉风格

贡献图必须匹配现有 `assets/blog-card.svg`、`assets/vlog-card.svg` 和顶部 GitHub stats 卡片的视觉语言：

- 背景、标题、正文、强调色沿用现有 Tokyo Night 色板
- 贡献格子使用同一色板的分级颜色，不使用默认 GitHub 绿色主题
- 贡献格色系保持 `#202a3d`、`#24515f`、`#38bdae`、`#70a5fd`、`#bf91f3`
- 格子内数字使用背景色 `#1a1b27`，形成从方格中镂空露出底色的观感
- 外框和圆角保持克制，避免额外渐变、发光、复杂装饰
- 标题和活跃天数保持克制，贡献格尽量铺满卡片宽度，避免左右留白明显大于上下留白

### 数据口径

使用 GitHub GraphQL `contributionsCollection.contributionCalendar` 获取过去 12 个月贡献数据。

由于用户希望尽量包含私有贡献计数，workflow 使用仓库 secret：

```text
GH_PROFILE_TOKEN
```

实现应说明：私有贡献是否计入最终结果，还取决于 GitHub 账号的个人设置和 token 权限。根据 [GitHub Docs: Contributions on your profile](https://docs.github.com/en/account-and-profile/concepts/contributions-on-your-profile)，私有贡献可以选择显示为匿名计数；生成器不应展示私有仓库名称或敏感明细，只渲染聚合后的每日贡献数。

### CI 隔离

贡献图更新必须使用独立 workflow，不并入现有 `Update Stats` workflow。

建议新增：

```text
.github/workflows/update-github-contribution-graph.yml
```

触发方式：

- 每天一次定时运行，在 GitHub 贡献图新增 UTC 日期格子之前执行
- 支持 `workflow_dispatch`

独立 workflow 只负责 GitHub 贡献图，避免和 Blog/Vlog stats 的更新频次、依赖和失败面互相耦合。

### 时间策略

根据 [GitHub Docs: Contributions on your profile](https://docs.github.com/en/account-and-profile/concepts/contributions-on-your-profile)，profile contribution graph 的贡献时间按 UTC 记录。为了避免 UTC 日期刚切换后生成一个还没有贡献的新方格，独立 workflow 应安排在 UTC 日期切换前运行：

```text
cron: "50 23 * * *"
```

这对应北京时间次日 07:50，距离 GitHub UTC 日期新增方格约 10 分钟。这样生成出来的图会停在即将结束的 UTC 日期，不会在 UTC 00:00 之后立刻渲染一个新产生的空格子。

实现时还应在脚本层做一层保护：如果 GitHub Actions 实际启动时间被延迟到 UTC 00:00 之后，生成器应仍然以最近一个已完成或接近完成的 UTC 日期作为显示截止日，避免把刚开始的新 UTC 日期作为最后一个格子。这个策略只避免“刚新增的空格子”，不伪造贡献；如果某个完整日期确实没有贡献，它仍应显示为零贡献。

## 设计方案

### 数据获取

新增脚本负责调用 GitHub GraphQL API：

- 输入：`GH_PROFILE_TOKEN`
- 用户名：`ceilf6`
- 时间范围：过去 12 个月
- 输出：贡献日历数据和聚合统计

建议将原始或归一化后的贡献数据写入 `data/github-contributions.json`，便于调试、回归测试和 SVG 生成复现。

脚本失败策略：

- token 缺失时失败，并输出明确提示
- GitHub API 返回错误时失败
- 数据结构缺失时失败
- 不因为单日贡献数下降而失败，因为贡献窗口滚动会自然移出旧日期

### SVG 生成

新增贡献图生成脚本，读取 `data/github-contributions.json` 并生成 `assets/github-contribution-graph.svg`。

生成器职责：

- 根据每日贡献数映射热力等级
- 生成 `1020x184` 的宽幅 SVG
- 使用现有 Tokyo Night 色板
- 在每个贡献格中显示每日具体贡献数
- 渲染标题和活跃天数
- 不渲染贡献总数、用户名、月份、星期、图例或生成时间
- 输出稳定、可 diff 的 SVG
- 对空数据生成明确失败，而不是生成误导性空图

建议保持贡献图生成器独立，不重构现有 `scripts/generate-svg-cards.py`。如果需要复用颜色常量，可以后续再抽取公共模块，不作为本次必要范围。

### README 集成

在 README 顶部简介段落后新增一个居中图片块：

```md
<p align="center">
  <img src="./assets/github-contribution-graph.svg" width="99%" alt="GitHub contributions" />
</p>
```

实际实现时可根据 SVG 视觉宽度微调 `width`，但不应把它插入现有三卡片 `<div>` 中。

### Workflow

新增独立 workflow：

- checkout 仓库
- 设置 Python 运行环境
- 安装最小依赖，如 `requests`
- 执行贡献数据获取脚本
- 执行 SVG 生成脚本
- 只在文件变化时提交

commit 风格可沿用现有自动提交：

```text
chore: update github contribution graph [skip ci]
```

workflow 需要 `contents: write` 权限以提交生成文件。

定时触发建议使用：

```yaml
schedule:
  - cron: "50 23 * * *"
workflow_dispatch:
```

## 测试与验证

实现完成后需要验证：

- 本地脚本能在设置 `GH_PROFILE_TOKEN` 时生成数据和 SVG
- token 缺失时错误信息清晰
- SVG 文件存在且不是空文件
- README 引用路径正确
- `node --test tests/*.mjs` 仍然通过
- 如新增 Python 测试，覆盖贡献等级映射、空数据处理和 SVG 基本结构

视觉验证至少检查：

- 贡献图和现有 Blog/Vlog 卡片色彩一致
- README 顶部不拥挤
- 宽幅图在 GitHub README 中可读
- alt 文案存在

## 非目标

本次不做以下事情：

- 不使用 `gitlyy.vercel.app` 或其他第三方动态图片 URL
- 不重构现有 Blog/Vlog stats 生成链路
- 不把贡献图 workflow 合并进现有 `Update Stats`
- 不展示私有仓库名称、提交标题或任何私有明细
- 不新增复杂前端页面或交互能力

## 风险

- 私有贡献计数是否显示取决于 GitHub 账号设置和 token 权限。
- GitHub GraphQL API 可能受 rate limit 影响，workflow 应输出可诊断错误。
- GitHub README 对 SVG 渲染有安全限制，生成 SVG 应避免脚本、外链字体和复杂交互。
- 每日 workflow 会产生自动提交，需要保持只在生成内容变化时提交。
