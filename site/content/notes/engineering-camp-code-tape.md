---
title: 26 字节工程营——code-tape 复盘
date: 2026-07-06
summary: 两周带队从 0 到 1 做出代码讲解录制回放产品 code-tape：组长视角的人员调度与 Harness 工程基建，开发者视角的录制/回放/云端/AI 字幕/WebRTC 主链路。
source: CSDN
sourceUrl: https://blog.csdn.net/2301_78856868/article/details/161597694
---

> 很感谢老师们在我每次对接时的及时回应、以及同学们的配合与工作
>
> 仓库地址：[github.com/ceilf6/code-tape](https://github.com/ceilf6/code-tape)

# 一、管理者身份

在学习了"项目管理"课程中的"学习型组织"概念后，结合我对 Harness 开发范式的理解，我毛遂自荐想担任组长一职，也很荣幸能被大家选上。下面我从**人力分配**以及**仓库管理**两个维度介绍我作为管理者的工作。

## 1、宏观规划

首先我作为组长，不仅要做好老师们、同学们的沟通工作，同时要时时刻刻对项目的进展进行宏观把握。

### 1.1、人员调度

考虑到咱们项目是异地多人协同开发，如果一开始没有统一任务、分支、CR 和合入规则，很容易出现重复开发、主干漂移和质量不可控。所以我直接选择 GitHub 作为协作基建，把时间留给产品主链路和工程质量建设。

在开发模式上，我参考 Google Chunk 的小粒度拆分思路，采用主干协作：先将 PRD 作为宏任务拆解，每个阶段再拆成多个微任务，并按照拓扑排序确保每个 issue 的前序工作都已经完成。每位同学认领任务后，从 `main` 拉出短生命周期分支或 fork 分支开发，通过小 PR、CR、质量闸门、维护者确认和 squash merge 回到 `main`。仓库不采用 Git Flow、GitHub Flow 或 GitLab Flow 作为主流程，详细原因可以查看仓库的决策记录贴 discussions/70。

接着每个同学在认领任务后到自己的 fork 仓库开发，完成后向主仓库发起 PR。PR 需要经过非作者同学 CR，以及下面会介绍的 repo-guard 通过后才能合入。为了让大家明确 CR 标准，我也沉淀了 Code Review 说明文档。

在任务分配上，我没有简单按人数平均拆分，而是给 issue 打上 score 工作量标签，并通过 CI/CD 工作流维护进度；同时也给每个 issue 打上 stack 技术栈标签，尽量兼顾同学擅长的方向和想做的方向。这样既能控制交付节奏，也能避免同学被分到完全不感兴趣的任务后影响质量和积极性。以上所有工作流程我都已经沉淀在「规范工作流流程」文档方便大家随时查阅。

### 1.2、敏捷开发

在同老师们确认项目周期只有 2 周后，我决策采用**敏捷开发**。原因很简单：如果等全部功能做完再验收，方向一旦偏了就来不及修正。所以我把项目拆成多个阶段批次发派任务，每个阶段结束后立即发包，并及时同 PM 等老师确认产品是否偏离。

接着我进行了技术模块分析，撰写了技术模块拆解，并根据模块拆解做初步排期（这些文档也同步到了项目 docs/ 目录下，方便需要时给予 Agent 完整上下文）。最终明确了一条主链路：竞品信息调研 → 技术方案敲定、模块拆分 → 录制链路 → 回放链路 → 加分项。

在我看来，软件工程敏捷开发的本质，就是先让 MVP 跑通，再持续矫正、打磨成真正可用的产品。这一点可以从咱们的[发包节奏](https://github.com/ceilf6/code-tape/releases)看出：

- **5.27** 发布了 P0 MVP 包
- **5.27** P1+ AI 字幕
- **5.30** P1 云端
- **5.30** P1+ 面试
- **5.31** 录制体验、AI 字幕、运行沙箱与多语言编辑器升级
- **6.1** 回放封面、活动时间轴、运行面板与工作流稳定性优化
- **6.1** 稳定版：多语言录制、运行沙箱、云端封面与回放交互修复
- **6.2** 稳定版：外部 ASR、封面导入导出与录制权限修复

这种小步快跑的方式，一方面能让老师及时看到阶段成果，另一方面也确保了新增功能出现异常后可以回滚到上一个稳定版本。

### 1.3、FrontAgent + Skills

同时为了方便团队同步进度和风险，我将我的个人代理 [FrontAgent](https://github.com/ceilf6/FrontAgent) 接入飞书开放平台后导入群聊，作为群助手辅助大家工作；并用 [ceilf6-skills/skill-lifecycle](https://github.com/ceilf6/ceilf6-skills) 创建了工作进度汇报技能 progress-reporter（前面链接的项目都是我之前日常开发、维护的，没有占用工训营过程中的时间，开箱即用）。

每天早上 10 点，群助手 FrontAgent 会执行 `/progress-reporter cron` 定时任务，向老师和同学们同步当前项目进展；如果有进度或质量风险，也能及时提醒。在项目后期，我又创建了 semgrep-scanner 静态代码分析技能，用于及时排查仓库中的 Blocker 和 Critical 问题。

### 1.4、技术选型与敲定方案

在有技术模块拆解后，如果没有确定模块间的边界与字段交互那么大家开发起来仍然是云里雾里。于是在第一阶段也就是竞品信息收集、产出了竞品分析文档之后，我利用仓库的 discussions 同大家进行了技术栈的选型与最终技术方案的敲定，确保了决策信息的可回溯、沉淀进入项目的**知识库**。

最终得到了「技术方案」文档，它是项目的开发基准，我在仓库基建的工程**提示词**中是这么强调的：

```
# 文档
1. docs/PRD.md 文档的权威性是最高的
2. 提交的代码不准背离 docs/技术方案.md 。若认为技术方案有任何错误，应通过 discussion 及时上报仓库维护者
```

## 2、仓库 Harness 工程

在学习了 [Anthropic](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)、[OpenAI](https://openai.com/index/harness-engineering/)、[ghuntley](https://ghuntley.com/loop/) 等关于 Harness 的文章后，我认为，Harness 不只是给 Agent 提供更多上下文，也不只是把 skill、MCP 接得更全。它更核心的是把模型**输出**纳入工程管控，再把检查结果反馈给下一轮输入，形成可观察、可回滚、可迭代的闭环。

这点在 Claude Code 源码的工程化中也有所体现，我也曾对此做过[博客分享](https://blog.csdn.net/2301_78856868/article/details/159995844)。

### 2.1、repo-guard

[repo-guard](https://github.com/ceilf6/repo-guard) 是我之前日常开发维护的代码审查工具，这次正好用于解决多人 + Agent 协作下的质量兜底问题。在咱们百余个 PR 中，它累计发表审批 300+，采纳率超过 95%。

同时我用 github pro 账号和 gpt plus 账号为仓库开启了 Copilot 和 Codex 的 CR，repo-guard、Codex、Copilot 三重保障组成对抗式 CR，尽量确保每一份合入代码都经过不同视角的审查。同时我在工程提示词中强调：

```markdown
# 工作
1. 每次开始任务前必须运行 `npm run quality:predev`
2. 在改代码前必须先运行 `npm run agent:bootstrap`
3. 创建分支以 feature/ , fix/ 或 chore/ 开头
4. 使用 Karpathy Guidelines 技能确保代码改动的高质量、精确性
5. 前端 UI 设计使用 frontend-design 技能
6. 启动本地 web dev server 必须用 `npm run dev`
7. 在改动后必须阅读 GitNexus 的建议
8. 发起 PR ，然后等待 GitHub Actions 运行（不用理会"需要CR通过"的错误，这是正常的）、repo-guard 和 codex 以及 Copilot 的评论后进行审查
```

这样能确保 Agent 不是"写完就结束"，而是会等待 repo-guard、Codex、Copilot 等评审意见，按评论继续完善，并再次等待下一轮评审。

如果说 Agent 循环的中断条件是 LLM 不再 `tool_call`，那么咱们 PR + CR 循环的中断条件就是：评审对本次 issue、每次更新 diff 和整个 PR 完整上下文都不再提出 bug comment。其中 repo-guard 的 CR 技能使用的是我之前开发的 [ceilf6-skills/code-reviewer](https://github.com/ceilf6/ceilf6-skills/tree/main/code-reviewer)。

### 2.2、知识库

我对项目 Harness Wiki 知识库构建最初选定了 GitNexus 和 OpenViking 两个工具（均为社区开源工具）。前者用于反馈每次代码改动的级联影响，辅助 CI/CD 把控整体质量；后者用于为开发代理提供仓库的渐进式上下文和持久化记忆。

但是 OpenViking 需要部署服务，也需要额外和组员同步使用方式。考虑到本项目周期短、人员多、交付压力大，我最终放弃 OpenViking，优先选择接入成本更低、反馈更直接的 GitNexus。目前仓库已经接入 GitNexus。它通过 MCP server 向开发 Agent 暴露代码图谱与影响分析能力，用来判断当前改动是否影响项目整体性。

### 2.3、Git hooks

在仓库工程基建中，我沉淀了很多质量脚本。它们的作用不是增加流程负担，而是把容易遗漏的检查前置到提交、推送和 PR 阶段。其中就包括通过 `core.hooksPath=.githooks` 接管的 pre-commit 和 pre-push，它们分别在代码提交和推送前自动执行质量闸门：

- `npm run quality:precommit` 覆盖仓库测试、Web lint、Web 单测和构建
- `npm run quality:local` 会刷新 GitNexus 索引，并执行完整本地质量闸门

### 2.4、SDD

SDD 在这个项目里不是单纯"多写几份文档"，而是把需求、方案、任务和 PR 约束变成 Agent 开发前必须读取、开发中必须遵守、开发后必须自证的工程契约。我的核心思路是：先用规范收窄问题空间，再让大模型在明确边界内做预期改动，避免它只根据局部代码自由发挥。这套 SDD 在仓库里主要落到四层：

- **产品规范层**：`docs/PRD.md` 权威性最高，负责定义 P0/P1/P1+ 的范围和验收口径；`docs/技术方案.md` 作为开发基准，明确事件流优先、iframe sandbox、本地录制包、回放不默认重跑代码等关键取舍。Agent 如果认为技术方案不合理，不能直接绕开实现，而是要通过 discussion 反馈维护者
- **决策追溯层**：关键取舍沉淀为 ADR 和 discussion，例如 Monaco、IndexedDB、seek 策略、WebRTC 和 AI 字幕的阶段边界。这样同学和 Agent 看到的不只是"结论"，也能追溯为什么当时没有选择另一条路
- **任务收敛层**：PRD 先拆成 issue，再由 issue 写清背景、验收标准、关联 PRD 章节和技术栈标签；对于复杂改动，我还通过 `docs/superpowers/specs/` 和 `docs/superpowers/plans/` 先写局部 spec / plan，把模糊需求变成可执行步骤后再动手
- **PR 契约层**：PR 模板要求填写改动点、影响范围、GitNexus 影响分析摘要和自检项；对于 `recording-schema`、`runtime-preview`、`replay-core`、workflow、权威文档等关键骨架，`contract:gitnexus` 还会要求匹配测试和结构化影响分析，避免"改了核心规则但没有说明影响面"

同时，开发中还使用 `/using-superpowers` 等 spec Skills，配合 OpenSpec-cli 工具，确保模型在动手前先理解需求、拆清取舍，收尾时再回到验证和评审。

因此，SDD 在这里承担的是"方向盘"的作用：它不直接保证代码一定正确，但能保证每次改动都能回答三个问题：为什么要改、允许改到哪里、怎么证明没有偏离。后面的 TDD、Git hooks、GitNexus、repo-guard、Codex 和 Copilot，则是在这个方向盘之后继续提供刹车、仪表盘和外部评审。

### 2.5、TDD

在这个项目里，TDD 不是单纯"多写测试"，而是把需求、实现和回归风险绑定在一起。我的要求是：每个功能先回到 PRD、技术方案和 issue 验收标准，先用测试刻画预期行为，再让 Agent 做最小实现，通过**红灯 → 绿灯 → 重构**收敛代码；重构阶段再配合 Karpathy-Guidelines，避免为了通过测试引入过度抽象或无关改动。仓库测试分成几层：

- **纯逻辑单测**：覆盖 `RecordingClock`、`EventBus`、`PackageBuilder`、`ReplayReducer`、`ReplayScheduler`、schema validator、hash 和 activity density 等模块。比如暂停期间不累计录制时长、seek 时只重放稳定事件、录制包 checksum 必须匹配，这些都适合用可控输入直接测试
- **组件与集成测试**：用 Vitest + Testing Library 覆盖编辑器、录制控制条、播放器控制条、云端列表、字幕面板、面试工作台等 UI 和业务组合，确保用户可见状态、按钮可用性和错误兜底不是靠手测维护
- **端到端测试**：用 Playwright 走真实浏览器路径，验证"开始录制 → 写代码 → 运行 → 暂停/继续 → 停止 → 保存 → 进入回放 → 播放/seek"的闭环。这个测试覆盖了内容变更防抖、鼠标轨迹、选区、快捷键、运行输出和回放 seek，是 P0 主链路可演示的关键保险
- **工作流契约测试**：`scripts/tests` 不只测业务代码，也测试 issue 认领、PR 合规、自动合并、GitNexus contract 和 workflow 配置。这样仓库规则本身也是被测试保护的，不会因为改脚本把协作流程改坏

这些测试会被上面提到的 git hooks 和 CI 质量门串起来：pre-commit 跑快速质量门，pre-push 跑完整本地质量门，PR 阶段再由 GitHub Actions 兜底。也就是说，TDD 在这里既保护功能正确性，也保护多人协作和 Agent 协作的工程边界。

### 2.6、形成循环、循循善诱

- 开发前先建立上下文和质量基线：`npm run quality:predev` 会安装 hooks、运行 `contract:local`，并刷新 GitNexus 索引
- 改代码前先收束任务边界：`npm run agent:bootstrap` 会提示 Agent 阅读 PRD、技术方案、GitNexus 建议和当前 issue，避免模型脱离仓库事实自由发挥
- 开发中用 TDD 控制改动粒度：先写或补齐能暴露问题的测试，再做最小实现让测试变绿，最后只在测试保护下重构，避免一次 PR 同时混入功能、重构和无关清理
- 开发中坚持小步提交：每个 issue 对应短生命周期分支或 fork 分支，通过小 PR 降低 CR 成本，也便于问题出现后快速定位和回滚
- 提交和推送前由 git hooks 做第一层兜底：pre-commit 跑快速质量门，pre-push 跑完整本地质量门，尽量把低级问题拦在本地
- PR 阶段由 GitHub Actions、repo-guard、Codex、Copilot 和人工 CR 做第二层兜底：只有当 issue、diff 和完整 PR 上下文都不再出现新的 bug comment，才进入合入流程

这就是我理解的 Harness：不是期待 Agent 一次性写对，而是把 Agent 放进可观察、可追责、可回滚、可持续修正的工程闭环里，循循善诱地把结果逼近正确。

# 二、开发者身份

从仓库的 Insights 可以看出，我不仅负责仓库基建，也参与了 P0 主链路、P1 云端能力和 P1+ 加分项的核心开发。

## 1、P0 MVP 基础功能

P0 阶段的问题不是"做一个普通代码编辑器"，而是验证 PRD 中"代码讲解可以被结构化录制并交互回放"这条主链路。两周周期内如果同时追求完整 IDE、后端沙箱、多文件工程和云端能力，很容易把 Demo 做散。

所以我把 P0 取舍收敛为"事件流优先、音视频辅助、iframe 沙箱展示、本地录制包优先"：先保证录制者能写代码、运行代码、讲解、开关摄像头与麦克风，结束后生成录制包；观看者再通过播放器按时间轴还原代码变化、鼠标轨迹、光标选区、快捷键、运行结果和摄像头画面。

### 1.1、编辑器与运行沙箱

这里的问题是编辑器不能只是一个输入框，它必须同时承担"可写代码"和"可采集事件"两个职责。取舍上我没有自己造编辑器，而是接入 Monaco Editor，让项目从静态 scaffold 进入真正可编辑、可录制的代码工作台。

实现上，编辑器支持 JS / TS 语法高亮、基础补全、语言切换、字号与主题等基础设置，并为内容变更、选区、快捷键采集提供稳定入口。代码运行没有选择高风险的后端容器沙箱，而是按 PRD"前端代码页面展示"路线，采用 iframe sandbox + postMessage 的前端运行方案。

兜底上，P0 不承诺 Docker 隔离、多语言执行、npm 依赖和完整工程运行。运行预览层把 HTML / CSS / JS 组织进 sandbox iframe 的 body / style / script 执行上下文；TypeScript 先做浏览器侧 transpile，再作为 JS 注入运行。

### 1.2、结构化录制链路

P0 最关键的问题是：录制的不是视频，而是带时间戳的事件流。如果事件时间、暂停偏移、媒体状态和编辑器状态分散在不同组件里，后续 seek 和回放一定会乱。

所以我选择把 `RecordingClock`、`EventBus`、`RecordingController` 和 `PackageBuilder` 作为录制事实源，编辑器内容、光标选区、滚动、鼠标轨迹、快捷键、运行结果、媒体状态都统一写入录制事件。

实现上，录制总控支持开始、暂停、继续、停止，并在录制过程中显示时长。媒体部分通过浏览器 MediaStream / MediaRecorder 采集麦克风和摄像头，并提供摄像头悬浮预览、开关与权限提示。录制结束后生成包含 meta、events、snapshots、media、manifest 的本地录制包。兜底上，本地包优先保存到 IndexedDB，同时提供导入导出和 quota 预检 / ZIP 兜底，避免 Demo 现场因为浏览器存储失败直接断链。

### 1.3、交互式回放链路

回放的问题是 seek：用户拖动进度条时不能从头线性播放到目标时间，也不能重新执行历史代码，否则结果不稳定、风险也更大。

所以我选择围绕 `ReplayScheduler` 和 `ReplayReducer` 做回放：播放器读取录制包中的事件、快照和历史运行结果，通过统一时间轴恢复任意时间点的稳定状态。

实现上，回放页支持播放、暂停、继续、倍速、进度条 seek、音量调节和静音；画面上同步还原编辑器内容变化、鼠标激光笔、光标选区、快捷键浮层、运行输出和摄像头视频。兜底上，如果媒体缺失，回放仍然保留纯事件流体验，不因为视频文件失败就放弃代码过程。

### 1.4、端到端验收与质量保障

为了避免 P0 只是模块可用、但主链路不可演示，我补齐了录制到回放的 Playwright e2e，用真实浏览器路径验证"开始录制 → 写代码 → 运行 → 停止 → 保存 → 进入回放 → 播放/seek"的闭环。同时，仓库中围绕 editorProducer、pointerProducer、shortcutProducer、mediaProducer、packageBuilder、recordingStore、ReplayScheduler、ReplayControls 等核心模块建立了单测和集成测试，确保事件流、录制包、回放调度这些高风险部分不是靠手测维持。

P0 阶段的结果是：项目已经从"方案和组件集合"推进到"可展示的代码讲解录制回放 Demo"。这条链路也为后续 P1 云端回放中心、P1+ WebRTC 实时面试和 AI 字幕留下了扩展点。

## 2、云端

在 P0 主链路完成后，我开始推进 P1 云端回放中心。PRD 对云端的要求是：录制完成后可上传至后端，支持列表查看、在线播放、删除和重命名；技术方案进一步明确云端不能另起一套录制格式，而是继续以本地 `RecordingPackageV1` 为事实源。

所以我在云端部分坚持一个边界：云端只负责上传、鉴权、对象存储、校验、索引、播放描述、分享和删除生命周期；真正的回放仍然复用 P0 已经验证过的事件流、快照、运行结果和 `ReplayScheduler`，不重新执行历史代码。

### 2.1、身份认证

早期 Demo 用 `x-owner-token` 做隔离，但问题是长期设备标识会出现在每个业务请求里。取舍上我没有把完整登录体系前置到 P1，而是把匿名身份升级成 refresh token / access token 两段式：长期设备 token 只用于换短期 Bearer token，真正的云端业务请求只带短期 token。

实现上，前端会在本地持久化一个 64 位 hex 设备 token，把它当作 refresh token，只在 `/api/auth/token` 里换取短期 Bearer access token；上传、列表、播放、重命名、删除、分享这些业务请求只带 `Authorization: Bearer ...`。服务端的 access token 是 `payload.signature` 结构，payload 里包含 `ownerId / iat / exp`，signature 用 HMAC-SHA256 签名，默认 15 分钟过期。前端会在过期前刷新，遇到 401 也会强制刷新并重试一次；如果刷新失败，不会退回去把长期设备 token 直接发给业务接口。

兜底上，服务端保留了 `x-owner-token` 的兼容路径，但只服务旧客户端。当前新版链路已经把"长期身份标识"和"业务访问令牌"拆开了，后续如果要接企业登录，也可以把 ownerId 的来源替换成真实账号，而不需要重写云端回放主链路。

### 2.2、云端上传与状态机

云端上传的问题是大媒体文件不能直接让 API 进程吞吐，而且上传失败、重复点击、对象损坏都需要可恢复。取舍上我采用 upload session 模型，把业务元数据和对象上传分离。

实现上，前端先把本地录制包拆成 `manifest / meta / events / snapshots / indexes / media / thumbnail` 等资产，逐个计算 sha256 和 size，再创建上传会话。服务端返回每个资产的 PUT upload target，前端直接把大对象上传到对象存储，最后调用 complete 触发校验。这个设计主要解决两个问题：

- API 进程不直接吞吐完整媒体 Blob，后续可以自然迁移到 S3 兼容对象存储、签名 URL 和 multipart 上传
- 上传会话带 `idempotencyKey`，断网重试时可以复用同一 session，不会因为重复点击上传污染云端列表

服务端状态机现在是 `uploading → processing → ready / failed`。validation worker 会读取对象存储里的资产，校验必需资产、checksum、schema、录制时长、事件数量和包大小；其中必需资产是 `manifest / meta / events / snapshots`，`indexes / media / thumbnail` 是可选资产。当前预算是录制时长 15 分钟、事件 20000 条、媒体 200MB、总资产 250MB。

兜底上，缺媒体时不会直接拒绝包，而是进入纯事件流回放能力。本地开发环境也补了对象存储 HTTP 适配层：PUT 上传、GET 下载、一次性 upload token、content-type 校验、上传大小限制和 CORS preflight 都有覆盖，保证前端本地调试和线上对象存储的行为尽量一致。

### 2.3、云端列表、播放、分享与删除

云端列表的问题是它不能只是"文件存上去了"，还必须能稳定播放、分享、删除，并且不能把未校验或已删除的录制暴露出来。取舍上我只让 ready 录制进入云端列表，上传中和 failed 状态不污染用户的正常观看入口。

实现上，前端回放中心有"本地录制 / 云端录制"两个 tab。本地录制可以上传到云端，上传时显示进度，完成后轮询云端校验状态；云端列表展示标题、封面、创建时间、时长、语言、音频和摄像头能力，并支持在线播放、重命名、删除和复制分享链接。

播放时前端不是直接拼对象 URL，而是先请求 playback descriptor。descriptor 会返回 `manifestUrl / metaUrl / eventsUrl / snapshotsUrl / indexesUrl / mediaUrl / thumbnailUrl` 以及过期时间；`CloudPackageLoader` 下载这些资产后，仍然走本地录制包完整性校验和 `ReplayScheduler` 播放。

分享链路也补齐了：owner 可以创建 `/s/:token` 形式的公开只读分享链接，并且可以带 `?t=` 时间点。分享播放不需要 owner token，服务端只用 token hash 找到 share link，再返回短期 playback descriptor；录制被软删后，关联分享链接会一起撤销。

兜底上，`indexes` 缺失时可以重建索引，`media` 缺失时降级成纯事件流回放。删除采用幂等 soft delete：第一次删除把状态改成 `soft_deleted`，写入 `deletedAt` 和 `purgeAfter`，列表、播放和分享立即不可见；重复删除会返回同一个软删结果，不会产生额外副作用。后续保留期结束后再进入对象清理流程。

### 2.4、部署服务器

云端能力的最后一个问题是：不能只停留在本地联调，必须有一个公网可访问的环境来验证上传、鉴权、列表和播放描述 API。取舍上我没有额外搭复杂运维环境，而是先用 Render Web Service 承载 P1 Demo。

实现上，我在 render.com 中新建 Web Service，连接 GitHub 仓库 ceilf6/code-tape，配置构建命令、启动命令和 Node 20，完成后得到线上部署地址 [code-tape.onrender.com](https://code-tape.onrender.com/)。验证请求：

```bash
curl -i https://code-tape.onrender.com/api/recordings \
  -H 'x-owner-token: demo-owner'
```

响应：

```yaml
HTTP/2 200
date: Sat, 30 May 2026 08:32:09 GMT
content-type: application/json
cf-cache-status: DYNAMIC
server: cloudflare
x-render-origin-server: Render

{"items":[],"nextCursor":null}
```

## 3、AI 字幕

我自学过神经网络、机器学习相关内容，之前也进行过[前端侧专业知识模型微调](https://hf.co/collections/ceilf6/frontagent-frontend-engineering-agent)，所以对这部分还是比较熟悉的。我把问题拆成两段：ASR 负责把音频变成带时间戳的字幕，LLM 负责把字幕里的代码术语、变量名和章节边界修正好。流程就是：音频 Blob → @huggingface/transformers → Whisper/ONNX → 浏览器本地 WASM/ONNX Runtime 推理；LLM 只做 ASR 后处理，不替代 Whisper 转写。

这部分我认为的技术难点主要在于模型输出稳定性、加载性能和浏览器资源竞争。

### 3.1、LLM 微调

考虑到信息的安全，AI 在本地也就是用户浏览器上运行，但是发现由于浏览器环境限制，导致 LLM 的参数不能很大，所以我就想着能不能通过用大模型进行蒸馏、配合前端语料进微调提高模型对咱们项目场景的适配度、从而提高输出质量。其中蒸馏数据生成器从 seed 样本调用 teacher API，产出 SFT JSONL。

在自测过程中发现"字幕生成"部分用的 [whisper-tiny](https://huggingface.co/onnx-community/whisper-tiny) ASR 模型准确率可以达到 90%。但后续"纠错并生成章节"这一步用到的 LLM，我按照预想用更强的 teacher model 蒸馏、并结合前端相关语料进行微调训练，拿到了[适配咱们项目的 ONNX 模型](https://hf.co/collections/ceilf6/code-tape)。

不过我跑了一晚上的语料生成和训练优化，早上测试后发现，"纠错并生成章节"的实际效果还是不太理想，尤其是在：

- 章节划分和语义纠错的稳定性
- 加载模型权重需要很长时间（我试过直接把模型直接打入 JS bundle 发现首屏响应时间长的离谱[捂脸]）
- 现在 LLM 已经放进 Web Worker，但 WASM/WebGPU 仍会吃 CPU/GPU/内存带宽，会和视频解码、浏览器渲染抢资源

于是我想到问题可能不出在微调训练语料上，可能还在 schema 约定上。我排查了一轮后发现输入和输出都叫 segments，但输入段带 startMs/endMs/text，输出段只能是 id/text。小模型容易直接复制输入 schema，所以会出现缺 text、带 startMs/endMs 的坏 JSON。所以我后面把训练和运行时的输入字段改成 inputSegments，让输出专用 segments，得到新的一版 v6 在同一组 30 个真实生成探针上达到了 30/30 可解析 JSON，而前一版 v5 只有 24/30。

### 3.2、LLM 增量支持

在本地 LLM 能跑通后，我又遇到了一个很现实的问题：ASR 字幕生成比较稳定，但是"纠错 + 章节生成"这一步很容易因为浏览器本地模型太小、token 预算太紧、WASM/WebGPU 抢资源而超时或输出坏 JSON。所以我没有直接推翻本地模型路线，而是做了一个增量方案：**外部大模型优先，本地微调模型兜底**。

如果用户没有配置外部大模型，就继续走本地模型；如果配置了 OpenAI 兼容接口或 Anthropic，就优先请求外部模型，用更强的提示词完成术语纠错和章节生成；如果外部请求失败、超时、返回非法 JSON，或者接口不支持浏览器跨域，就自动回退本地模型，保证字幕和回放不会被中断。

因为模型请求里带了 `Authorization`、`x-api-key`、`content-type: application/json` 这类非简单请求头，所以浏览器命中了 CORS 同源策略，会先发预请求 preflight，只有目标接口允许跨域，页面才能拿到结果。所以我在页面中强调了需要"填支持浏览器跨域（CORS）的请求地址"。

目前我把 Key 只保存在用户本机 `localStorage`，不写进仓库、不打进 bundle、不发给 code-tape 后端；HTTP 错误也不读取响应体，避免错误配置的网关把 Key 或字幕上下文回显出来。

### 3.3、ASR 输出

ASR 调用 `onnx-community/whisper-tiny` 时，如果不显式指定语言，模型很容易把中文讲解识别成英文或拼音，尤其是中英混合的代码术语场景。所以我后面把 ASR 参数固定为 `task: "transcribe"` 和 `language: "chinese"`，先让 Whisper 明确按照中文讲解去转写；React、TypeScript、useState 这类代码术语，再交给后面的 LLM 后处理修正。这样分工会更稳定：ASR 负责带时间戳的原始字幕，LLM 负责术语纠错和章节。

同时在测试过程中发现拉取 ASR 模型权重矩阵时间过久，进行了三项改进：提前进行预热加载（在组件挂载后就立即去请求模型）；复用 LLM 以微调模型进行兜底的逻辑，ASR 现在也支持调用外部模型；优化阶段信息显示，起到加载条的效果，防止用户等待途中的焦急心理。

### 3.4、模型托管

上线测试时还暴露出一个工程问题：不是每个使用环境都能稳定访问 Hugging Face，模型权重拉不下来时，字幕功能会卡在加载阶段。

于是我把默认 ASR / LLM 模型资产通过 `npm run subtitle:vendor` 拉到 `apps/web/public/` 下，让线上页面优先从同源静态资源加载。这样一方面绕开了 huggingface.co 网络不稳定的问题，另一方面同源加载也不会再被浏览器 CORS 卡住。构建前还有 `verify-vendored-assets` 检查，避免模型文件缺失时直接发版。

### 3.5、产品体验优化

感谢 PM 老师的建议，这里我把字幕能力从"多个技术按钮"收敛成了一个主按钮：用户只需要点击一次，系统先跑 ASR，并且马上把原始字幕展示出来；随后后台继续跑 LLM 纠错和章节生成，成功后自动二刷字幕和章节。

这样即使 LLM 慢或者失败，用户至少已经有可看的字幕；而且字幕行和章节都可以点击 seek，最终还是回到项目最核心的交互式回放体验上。

## 4、前端沙箱隔离

PRD 里代码执行给了两条路线：后端沙箱执行，或者前端页面展示。考虑到两周周期和 Demo 风险，我选择了 iframe sandbox 前端展示路线，而不是一开始就做 Docker / V8 isolate 这种重型后端沙箱。

### 4.1、iframe 沙箱隔离

可执行 JS/TS 默认创建 `<iframe sandbox="allow-scripts">`，只允许脚本执行，不默认加 `allow-same-origin`、`allow-popups` 等能力，所以用户代码运行在 opaque origin 里面，不能拿宿主同源权限，弹窗也不会按正常浏览器窗口能力开放。

每次运行都会创建新的 iframe 和随机 `runId`，旧的会被 `teardown()` 移除，避免多次运行复用脏状态。并且 `runtimeProducer` 中传入 `timeoutMs` 超时限制，防止 `setInterval`、异步 flood、DOM 增长等超时后继续消耗资源。同时 iframe 内的 boot script 会：

- 劫持 console.log/warn/error 并转发给父页面
- 监听同步 error
- 监听 unhandledrejection
- 覆盖 alert/confirm/prompt，改成返回安全值并上报 blocked-alert

所以用户代码触发弹窗不会真的打断宿主 UI，而是变成运行输出里的 blocked 信息。

### 4.2、CSP 策略限制能力

可执行 iframe 的 srcdoc 注入 CSP：

```
default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none';
```

默认拒绝所有资源，脚本只允许内联执行，样式只允许内联样式，图片只允许 data: / blob: 格式，网络连接被 `connect-src 'none'` 禁用。在回放时直接使用 `script-src 'none'` 禁止脚本执行，只展示录制时保存下来的 preview 结果，避免观看者打开回放时重新执行历史代码。

### 4.3、子 → 父

因为 sandbox iframe 是 opaque origin，子页面向父页面发消息只能用 `postMessage(..., "*")`。仓库没有把 `*` 当信任边界，而是在父页面做多层校验：

- source 必须是 code-tape-runtime
- runId 必须匹配当前运行
- event.source 必须是当前 iframe 的 contentWindow
- type/payload 必须符合 schema
- 允许的消息类型只有 ready、console、error、blocked-alert、complete

### 4.4、父 → 子

宿主给 iframe 发送用户代码时，不直接靠普通窗口 postMessage 广播，而是 iframe boot 时创建 MessageChannel，把控制端口交给父页面；后续 init 和 set-theme 都走这个私有 MessagePort，减少普通 window.postMessage 广播带来的混杂风险。

### 4.5、社区成熟 DOMPurify 工具库

静态 HTML / 回放 preview 在写入 no-script iframe 前会先用 DOMPurify 清洗，并保留整文档解析能力。兜底上，回放 preview 永远进入 iframe，不直接写入宿主页面 DOM。

## 5、WebRTC 实时面试

WebRTC 这部分最大的问题是范围控制。如果把它做成多人协同编辑，就必须引入 CRDT / OT、冲突解决和权限模型，复杂度会直接变成协同 IDE。所以我的取舍是严格收敛成 PRD 里的实时面试模式：候选人是唯一写入者，面试官只是实时只读观察者。这样既能体现"实时看代码讲解"的加分能力，又不会把 P1+ 做成另一个协作 IDE。

### 5.1、面试房间与 WebSocket 信令

实时面试首先要解决的是双方怎么进入同一个会话，以及 WebRTC 怎么完成建连。这里我没有让 WebSocket 承载持续代码事件，而是把它限定成信令通道。

实现上，候选人创建面试房间，服务端生成 `roomId / joinCode / signalingUrl`。候选人和面试官通过 WebSocket 交换 `join / offer / answer / ice-candidate / heartbeat / leave` 等消息，完成 SDP / ICE 协商后再建立 WebRTC 连接。兜底上，信令层只做房间、身份、连接消息校验和转发，不长期保存 SDP 内容；如果连接失败，UI 可以保留最近状态并进入重连，不影响候选人本地录制链路。

### 5.2、音视频与 RTCDataChannel 分流

建连后的问题是通道职责不能混在一起：音视频是媒体流，编辑器事件是结构化高频数据，如果都塞进 WebSocket，信令服务就会变成实时数据通道。

所以我把链路拆开：音视频走 WebRTC media track，候选人和面试官可以双向通话；编辑器事件走 `RTCDataChannel`，用于同步内容变更、选区、快捷键、运行结果等结构化事件。兜底上，WebSocket 只保留控制和建连职责，DataChannel 负责高频事件；如果未来公网 NAT 穿透失败，再补 STUN / TURN 或临时把编辑事件降级走 WebSocket。

### 5.3、候选人单写与 P0 事件流复用

这部分最重要的取舍是"不重新发明一套实时事件协议"。候选人端已经有 P0 录制链路，如果 WebRTC 再单独生成一套事件，就会出现实时状态和回放状态不一致的问题。

所以我让候选人端继续使用原来的 `RecordingController`、`EventBus` 和 `PackageBuilder`。`InterviewSyncPublisher` 只订阅已经产生的录制事件并转发给面试官，不自己改时间戳、不改 seq。兜底上，候选人仍然是唯一写入者；面试官没有写权限，所以不需要处理多人编辑冲突。面试结束后，候选人本地录制包仍然可以按原链路保存或上传云端。

### 5.4、面试官只读工作台

面试官侧的问题是：实时看到的代码状态不能和回放播放器各算各的。否则同一个事件流，在实时页和回放页会产生两套解释逻辑。

所以面试官端复用 `ReplayReducer / ReplayStableState` 渲染只读工作台，用和回放一致的 reducer 解释候选人事件。这样"实时看到的状态"和"回放看到的状态"来自同一套状态模型。兜底上，面试官工作台只读，不触发候选人写事件；如果面试官刷新页面，重新加入后也可以通过候选人最新 snapshot 恢复只读状态。

### 5.5、抖动缓冲与快照重同步

网络层最大的不确定性是乱序、丢包和短断。面试官端如果"收到一条就渲染一条"，状态会被网络到达顺序污染。

所以我做了一个小型的 `RemoteTimelineBuffer`：面试官端不按本地到达时间直接渲染，而是按候选人事件的 `seq` 和 `timestampMs` 做小延迟播放；如果发现 seq 缺口或 hash 不一致，就请求候选人发送最新 snapshot，再从 snapshot 之后继续重放事件。

兜底上，这套策略不解决多人编辑冲突，因为实时面试本身就是单写者模型；它解决的是网络抖动下只读观察者状态最终一致。核心就是：**单写者 seq + 小延迟缓冲 + 周期快照 + hash 校验**。

## 6、体验打磨与工程收尾

除了主链路和加分项，我后面也补了一批体验和工程稳定性问题。这部分的问题是：Demo 能跑不等于现场好用，窄屏、拖拽、主题、封面、CI 和自动合并这些细节如果不收尾，很容易在展示或协作时暴露。

所以我把这类问题按"用户可感知体验"和"工程协作稳定性"两类处理：前者优先影响录制、回放、库页和整体工作台的使用感（工作区拖拽分配空间、视频最后帧封面、窄屏响应式、主题跟随系统等）；后者优先保证 CI、自动合并、仓库提示和安全扫描不反复打断开发节奏（LFS checkout 修复、自动合并阻塞修复、GitNexus contract 缓存稳定、Semgrep 告警清理等）。

> 全部 issue/PR 编号对照、演示视频与截图见 CSDN 原文。
