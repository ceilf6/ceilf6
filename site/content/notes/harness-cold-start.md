---
title: 关于 Harness 的讨论，附冷启动工具
date: 2026-07-27
summary: 我如何在仓库里搭建 Harness 环境：TDD 质量门、知识库、SDD 与 CR 机器人，以及沉淀出的冷启动工具 harness-kit。
source: LinuxDo
sourceUrl: https://linux.do/t/topic/2481591
---

想聊聊 Harness。在我看来，Harness 是进行良好 Loop 的前提环境。我一般在开发前都会先在仓库构建我认为的 Harness 环境：

- **TDD**：通过工程提示词引导方向，要求智能体在每个功能完成之后写冒烟 / e2e 测试文件（具体看任务场景），然后通过 Git hooks 在推送和提交前的质量门中运行。
- **知识库**：用社区中的例如 OpenViking、GitNexus 等给智能体开眼睛（具体看仓库需要哪种程度、什么方向的知识上下文）。
- **SDD**：更多是在开发过程中调用 superpowers 等工具，同时结合上面的知识库进行规范代码的级联反应等等。
- **CR 机器人**：我用的是我自己开发的 [repo-guard](https://github.com/ceilf6/repo-guard)。虽然一开始在社区中找过类似的、不想重复造轮子，但是感觉不是很符合我的场景，于是我自己弄了一个、调了提示词，虽然一开始感觉有些问题但是随着迭代越用越舒服。

有了环境之后，在 codex/cc 中设个 /goal 或者在 cursor 中用 /loop 就能朝着一个目标跑很久的循环，过程中智能体会按照工程提示词的要求：issue → dev → PR → CR [if bug → dev → update PR → CR → …]

工程提示词我一般都是按照 [AGENTS.md](https://github.com/FrontAgent/FrontAgent/blob/develop/AGENTS.md) 的风格来，适合 OSS。

最近将上面这些经验总结了一个冷启动工具：[harness-kit](https://github.com/ceilf6/harness-kit) —— Harness 工程冷启动 CLI，用于快速在一个仓库中搭建 Harness 环境。

欢迎交流 Harness、给我提提 bug。
