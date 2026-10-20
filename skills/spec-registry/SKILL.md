---
name: spec-registry
description: 多 Agent / 多任务并行开发时的 SPEC 治理与 git worktree 协调。当同一项目里有多个任务或 Agent 同时发 SPEC、改代码,需要登记 SPEC、声明 impact_scope、检测范围冲突、按 Epic 复用 worktree、按 A设计/B验证/C开发/D审核 流转、人类签发、登记验证证据、越界拦截时使用。关键词:SPEC Registry、workspace.sh、impact_scope、attach、check-scope、epic worktree、SPEC 冲突、多 Agent 纪律。单人单任务的普通开发不要用。
---

# SPEC Registry

所有操作只通过项目里的 CLI 完成,不要手写 git worktree / 分支命令,也不要手改状态文件:

```
./scripts/spec-registry/workspace.sh <命令>      # Windows: scripts\spec-registry\workspace.cmd
```

文件 `scripts/spec-registry/workspace.py` 不存在时,说明项目还没初始化:让用户运行 `install.sh --init`,不要自己造脚本。

## 开工前(任何角色)
1. 先读全局:`workspace.sh overview`(一行一个 SPEC,L0)。
2. 要深入某个 SPEC:`workspace.sh related --spec <ID>`(L1,只加载相关的)。不要整份读完所有 SPEC。
3. 确认自己的角色和模型底座:环境变量 `SPEC_ROLE`(A/B/C/D/H)、`SPEC_AGENT`、`SPEC_MODEL`(glm / gemini / claude / gpt / deepseek)。不确定角色就问用户,不要猜。

## 各角色只做自己的事
- **A 设计**:`new-spec` → 填 frontmatter(`impact_scope`、`risk`、`depends_on`、`required_evidence`)→ 提交到主分支 → `transition <ID> verifying_spec`。禁止改业务代码。
- **B 验证**:核对 SPEC 与实现的客观事实;`evidence` 登记证据;`transition` 推进或退回。不得验证自己写的东西。
- **C 开发**:`attach --epic <e> --spec <ID>` 认领并进入沙箱;只在返回的 `.worktrees/epic-<e>/` 里改文件,只改 `impact_scope` 声明的文件;随时 `check-scope`;长任务 `heartbeat` 续租;完成后 `transition <ID> verifying_impl`。禁止自建分支/worktree,禁止把自己的工作标为通过。
- **D 审核**:独立判断设计与实现的质量和风险;`finish --epic <e>` 终审收尾。HIGH/CRITICAL 下必须与 A、C 不同底座。
- **H 人类**:`signoff` 设计与发布签发。模型不得代签。

## 硬规则
- 脚本报错就停下来读错误信息,按提示补条件;不要绕过(不要 `--force`,除非用户明确同意并写明原因)。
- 改了 SPEC 正文或 `.meta.yml`,批准和签发自动作废,必须退回 draft 重新提交。
- 分支有新提交,证据和发布签发自动过期,必须重新登记。
- 小改动可用 `track: lite`(免 D 设计审核和人类签发),只限 LOW/MEDIUM 风险。把风险标低来躲签发是违规。
- 证据按类别登记,不外推:handler 测试通过不等于浏览器端到端通过。

## 更多细节(按需读取)
- 状态机、每步的脚本检查:`references/workflow.md`
- 各角色职责与边界:`references/roles.md`
- 常见报错与处理:`references/troubleshooting.md`
- 命令全表:`workspace.sh --help`
