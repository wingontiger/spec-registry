# 设计说明

## 两层结构

| 层 | 位置 | 入库 | 回答的问题 |
|---|---|---|---|
| 运行时协调层 | `workspace.py`,状态在 `.git/spec-registry/` | 否 | 现在谁在改什么、谁能改、卡在哪一步 |
| 治理索引层 | `registry/spec_registry.json` | 是,经受保护 PR | 哪份 SPEC 被授权、哪些证据支持它 |

SPEC 正文在 `.specs/`(入库,设计在主分支完成后才开发)。运行时层的状态不写进 SPEC,避免每次状态变化都产生提交和合并冲突;两者靠 SPEC 内容哈希对齐。

## 来源与取舍

| 来源 | 采纳 | 修改或不采纳 |
|---|---|---|
| Gemini(找回的早期版本与两份 PDF) | Epic 复用 worktree、`impact_scope` 四类字段、SPEC frontmatter、`workspace.sh` 命令集、pre-commit 硬门禁与孤儿分支检查、L0/L1 分层摘要、"厚内核 + 薄 skill"的形态 | 修复脚本漏洞(沙箱内读不到主工作区的 SPEC、只看 `git status` 导致提交后越界检查失效、`finish` 状态替换不生效且 `--force` 删除未合并工作、`registry.json` 入库导致合并冲突、`split('---')` 解析);L3 心跳总线划给 peer-relay;MCP server 暂不做 |
| ChatGPT(历史核查与治理工具包) | 入库 canonical 索引与 CI 检查器(原样收入)、SPEC 内容哈希、人类签发证据、审查独立性、证据类别、单元级依赖、`discovered` 采纳不假设已批准 | 签发做成状态机门禁,并绑定 SPEC 哈希或提交,变化即失效 |
| Claude(v0.1 起) | 状态机与角色分离、租约、范围冲突检测、实际 diff 校验 | 扩展为 A/B/C/D + 人类 H |

## 状态机

见 `skills/spec-registry/references/workflow.md`。

## 为什么不是 MCP

Gemini 建议"CLI + MCP 插件 + 薄 skill"。薄 skill 与 CLI 采纳了;MCP 暂不做:Claude Code、Cursor、Codex、Antigravity 都能直接执行 shell 命令,命令行本身已经是确定性的接口。MCP 会多一个常驻进程、一套工具 schema 和一份跨工具的配置要维护,收益只在没有 shell 的环境里。

## 与 Gemini 说法不一致或需要保留意见的地方

- "每个 Worktree 的 Agent 会话上下文天然独立":worktree 只隔离文件系统。会话上下文是否独立取决于你怎么开会话,不是 worktree 保证的。
- 对 Antigravity 的 `/fork`、`/agent`、hooks 等能力的描述来自 Gemini 引用的资料,我没有核实,本 skill 不依赖它们;硬门禁用的是 git 自带的 pre-commit hook,与具体工具无关。
- "各厂商没做是因为商业和 Token 经济学"属于推测,不影响设计。
