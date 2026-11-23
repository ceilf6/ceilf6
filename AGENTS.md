# ceilf6 个人站

## Harness Loop

每个开发小步交付一个可独立验证的结果。执行顺序为 Issue → 短分支开发 → PR → 独立 CR → 自动合并 → 下一步。

1. **开 Issue。** 创建或复用本步的 GitHub Issue，写明要解决的问题、预期结果和验收办法。一个小步对应一个 PR。
2. **从最新主线开发。** Fetch 后从 `origin/main` 建短分支，命名沿用仓库惯例。检查相关调用方和已有测试，只提交本步涉及的文件。SDD spec 与 plan 保留在本地。
3. **验证后提 PR。** 运行本步相关的本地检查，正常提交、推送并向 `main` 提 PR。正文用 `Closes #编号` 关联 Issue，说明实际改动和验证结果。
4. **委托独立 reviewer 开放式 CR。** 请 reviewer 自主审查整个差异及受影响路径，并给出结论和依据。Issue 的验收条件供复现用，reviewer 可以提出任何方向的问题。
5. **在原 PR 修正。** 阅读 CI 结果、review 和讨论线程。修复成立的问题，对其他意见给出可核对的处理依据。HEAD 变化后复跑相关检查，请独立 reviewer 评审新版本。
6. **每步通过后自动合并。** 开发 agent 核对最新 HEAD 的适用 CI 已通过、独立 CR 已明确通过、所有待解决问题已处理且分支可合并，随即 squash 合入 `main`，无需维护者逐步确认。可执行 `gh pr merge "$pr_number" --squash --match-head-commit "$reviewed_sha"`，将合并绑定到评审通过的 SHA。若 HEAD 变化或发生冲突，更新分支并重新验证、评审。
7. **回读后开始下一步。** 确认 PR 状态为 `MERGED`、合并提交已进入 `origin/main`、关联 Issue 已关闭。下一小步从新的主线开始，Git 历史中每步保留一个有意义的提交。

## 验证与发布

- 前端位于 `site/`。在该目录运行 `npm run type-check`、`npx vitest run` 和 `npm run build`。发布脚本变更在仓根运行 `python3 -m unittest discover -s deploy/tests -t .`。根据本步涉及的目录选择检查，PR 上以实际运行的 Verify 工作流为准。
- Repo Guard 承担 CR 时，读取对当前 PR 版本的评审正文和结论。若本次未产出有效评审，委托其他独立 reviewer 补审。CI 成功与 CR 通过分别核对。
- 合并触发 ECS 静态发布时，跟踪该合并提交的发布结果。下一步依赖线上行为时，先从公开域名验证。发布入口和触发路径见 [deploy/README.md](deploy/README.md) 和 [部署工作流](.github/workflows/deploy-ecs.yml)。
