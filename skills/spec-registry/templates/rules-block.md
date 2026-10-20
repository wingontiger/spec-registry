<!-- spec-registry:begin -->
## 多 Agent 协作纪律(spec-registry)

所有任务、SPEC、worktree 的操作只通过 `./scripts/spec-registry/workspace.sh`(Windows: `scripts\spec-registry\workspace.cmd`)完成。

- 禁止自行执行 `git worktree add`、`git checkout -b epic/...` 或手改状态文件。
- 开工前先 `workspace.sh overview` 看全局,再 `related --spec <ID>` 按需深入;不要通读所有 SPEC。
- 每个会话设置环境变量:`SPEC_ROLE`(A/B/C/D/H)、`SPEC_AGENT`、`SPEC_MODEL`(glm / gemini / claude / gpt / deepseek)。不确定角色就问用户。
- A 设计:`new-spec`,填好 `impact_scope`、`risk`、`depends_on`,提交到主分支后 `transition <ID> verifying_spec`;不改业务代码。
- B 验证:核对事实,`evidence` 登记证据,推进或退回;不验证自己写的内容。
- C 开发:`attach --epic <e> --spec <ID>`,只在返回的 `.worktrees/epic-<e>/` 内改动,只改 `impact_scope` 声明的文件;完成后 `transition <ID> verifying_impl`;不得自己标记通过。
- D 审核:独立判断质量与风险;`finish --epic <e>` 收尾。HIGH/CRITICAL 须与 A、C 不同底座。
- H 人类:`signoff` 签发,模型不得代签。
- 小改动可用 `track: lite`(仅 LOW/MEDIUM);把 `risk` 标低来躲签发属于违规。
- 报错就停下读错误信息,不要用 `--force` 绕过,除非用户明确同意。
<!-- spec-registry:end -->
