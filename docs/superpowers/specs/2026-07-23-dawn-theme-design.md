# 黎明晨光版个人主页 · 设计文档

日期：2026-07-23
状态：已与用户对齐（卡片不动、深色调暖调亮、viewer 同步；**简历仓库本次不动**，链接更新暂缓）
注意：本文档按用户惯例**不提交、不推送**。

## 目标

1. index.html 首屏文案中文化，使用真名「王景宏」。
2. 页面从"午夜蓝"调成"黎明晨光"：保持深色基底，但整体更暖、更亮，橙金光晕加强。
3. viewer.html 背景色同步黎明色调，点开奖状不跳戏。
4. 部署到 wangjinghong.com（push main 即自动发 ECS），简历中的主页链接同步更新。

## 非目标（明确不做）

- 四张 README 卡片 SVG（stats / huggingface / vlog / blog）不动。
- `scripts/` 下三个卡片生成脚本不动（CI 定时重刷，保持深色原样）。
- README.md、blog.html、vlog.html 不动。
- **简历仓库 `/Users/bytedance/Desktop/resume` 本次完全不动**（用户明确暂缓；
  将来更新时改 `src/data.tsx:254-255` certUrl/certUrlText 及 `src/data.test.ts:8-9`）。
- 不配置 HTTPS 证书（需要 SSH 权限，本次范围外，见「已知问题」）。

## 文案

- 标题 h1：`👋 Hi there, I'm ceilf6!` → `👋 你好，我是王景宏！`
  - 「王景宏」用 `.accent` 渐变强调，字体仍走 "ZCOOL XiaoWei" 书法体栈。
- 提示语（实施后变更）：hint SVG 起初重制为中文暖金流光版并已上线，随后用户反馈
  「不够美观」，已从 index.html **整体移除**（.readme-hint 结构与样式一并删除）。
  `assets/hint-text-for-index.svg` 文件保留在仓库（README 中有注释引用），不再被页面使用。
- 新增（用户追加需求）：页面底部 ICP 备案号页脚 `浙ICP备2026055968号-1`，
  链接 https://beian.miit.gov.cn/，muted 小字、悬停金色。

## 配色（index.html）

设计概念：黎明时分的天空。深蓝基底提亮一档、色温调暖；橙金光晕压向"地平线"；
加入淡紫晨霞光斑，让卡片自带的紫 #BF91F3 读起来像天空配色的一部分。

| 令牌 | 现值 | 新值 |
| --- | --- | --- |
| --bg-void | #050914 | #0B1226 |
| --bg-deep | #0C1730 | #14224A |
| --bg-midnight | #132541 | #1D3057 |
| --text-main | #EEF4FF | #F5F8FF |
| --text-muted | #AFC3DD | #C2D2EA |
| 主交互强调（原 --accent-cyan #57E3CF） | 青色 | 阳光金 #FFC069 |
| 次强调（--accent-amber） | #FFB262 | 朝霞橘 #FF9A62 |
| 新增晨霞紫 | — | rgba(191,145,243,≈0.14)（仅光斑用） |

应用规则：

- 所有青色交互反馈统一换成阳光金：卡片/相框悬停描边与光圈、加载圈、::selection、
  滚动条 hover、focus-visible 描边、readme-section 渐变描边（金 → 晨霞紫）。
- 背景三层 radial 光晕：琥珀层加强（透明度 0.24 → ≈0.32）并压低位置成"地平线晨光"；
  原青色层改为晨霞紫层；浮动光斑（body::after）同步换成金/橘/紫三色。
- 面板与卡片底色整体提亮一档并调暖（如 rgba(8,19,36,…) → rgba(13,22,44,…) 一类），
  网格噪点叠加层的冷蓝线条微调暖。
- 标题 .accent 渐变：琥珀→青 改为 阳光金 #FFCF87 → 朝霞橘 #FF9A62。

签名元素只保留一个：**地平线晨光**（页面底部缓慢浮动的暖金光带，复用现有
floatOrbs 动画机制，prefers-reduced-motion 下静止）。其余保持克制，布局、
瀑布流逻辑、动画结构一律不动。

## viewer.html 同步

只换色值，不动结构：

- 背景 rgba(12,25,41,.98) → 黎明navy（调暖提亮，如 rgba(13,22,44,.98)）。
- 图片光晕阴影 青(56,189,248)/紫(139,92,246) → 金(255,192,105)/紫（紫保留）。
- 加载圈青色 → 阳光金；导航按钮 hover 的天蓝 → 阳光金。

## 部署

本仓库改动完成、本地验证后，**单条干净 commit** 推 main（不含本 spec/plan 文档），
GitHub Actions 自动 tar 发 ECS `/var/www/wangjinghong`。

## 验证

- 本地：起静态服务器用 Playwright 截图检查 index.html 与 viewer.html（首屏文案、
  背景色调、卡片悬停、奖状查看器），prefers-reduced-motion 与窄屏断点抽查。
- 部署后：`curl --resolve wangjinghong.com:80:47.103.28.157 http://wangjinghong.com/`
  确认新文案已上线（本机 DNS 走代理 fake-IP，必须用 --resolve 验证）。

## 已知问题

- ECS 只监听 80，**443 无证书**，对外链接目前只能走 `http://wangjinghong.com/`。
  建议后续上机器跑 certbot 配免费证书；届时再做暂缓的简历链接更新，直接用 https。
