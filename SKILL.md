---
name: spec-registry
description: >
  多任务并发 SPEC 生命周期治理。在同一仓库下有多个任务/Agent 各自发出、
  执行、完成 SPEC 时，维护统一的 .specs/ 元数据账本，提供冲突检测、
  Epic worktree 隔离沙箱、scope 门禁和轻量并发心跳。

  当用户提到以下任一情况时触发：
  - "SPEC 注册表"、"SPEC Registry"、"建立 SPEC 追踪"
  - "多任务 SPEC 管理"、"跨任务 SPEC 感知"、"SPEC 冲突检测"
  - "Epic worktree"、"attach 工作目录"、"scope 校验"
  - "任务 A 怎么知道任务 B 的 SPEC 状态"
---

# Spec Registry

用于多任务并发开发的 SPEC 生命周期治理工具。

## 架构

三层分离，数据单向流动：

```
.specs/              ← L2 静态契约（source of truth，提交到 Git）
  SPEC-001.md          个人 SPEC 详情（YAML frontmatter + Markdown）
  registry.json        生成的机器可读索引（勿手动编辑）
  SPEC-OVERVIEW.md     生成的 LLM 注入摘要（勿手动编辑）

.worktrees/          ← L1 物理沙箱（gitignore，瞬态）
  epic-<slug>/         按 Epic 复用，不按 SPEC 新建

.sync/               ← L3 并发心跳（peer-relay-v3 管理，gitignore）
```

**核心约束**：
- `SPEC-NNN.md` 文件是唯一事实来源，始终由人工或 Agent 编辑
- `registry.json` 和 `SPEC-OVERVIEW.md` 由 `sync` 命令生成，永远不手动编辑
- worktree 按 Epic 分配（一个 Epic 一个 worktree），不按单个 SPEC 分配
- relay 交接由 **peer-relay-v3** skill 负责；本 skill 只做轻量并发心跳

## Agent 强制 SOP

### 会话启动（必须）
```
1. 读取 .specs/SPEC-OVERVIEW.md（L0 全局状态）
2. 读取 .specs/registry.json，检查 active SPECs 的 impact_scope
3. 与本次任务的目标模块/文件做交集
4. 有交集 → 向用户报告潜在冲突，等待确认
```

### 发出新 SPEC（必须）
```
python spec_registry.py check --module <path> [--task-id <TASK-X> 排除自己]
python spec_registry.py new --title "..." --task-id TASK-X --epic <epic> \
       --owner "..." --summary "..." --module <path> --file <file>
```

### 进入开发（必须）
```
python spec_registry.py attach --spec SPEC-001
# 此后只在 .worktrees/epic-<slug>/ 内编辑代码
```

### 开发中（推荐）
```
python spec_registry.py heartbeat --spec SPEC-001 --focus "..." --tool codex
python spec_registry.py check-scope --spec SPEC-001 --base main  # 软警告
```

### 完成交付（必须）
```
python spec_registry.py check-scope --spec SPEC-001 --base main --strict  # CI 门禁
python spec_registry.py set-status --id SPEC-001 --status Completed
python spec_registry.py sync
python spec_registry.py finish --epic <epic> --base main
```

### 需要 relay 接力时
→ 使用 **peer-relay-v3** skill 的 `handoff` 命令，不要用本 skill 的 heartbeat。

## 全部命令

```bash
python spec_registry.py init
python spec_registry.py new   --title "..." --task-id TASK-A --epic auth \
                               --owner "Agent A" --summary "..." \
                               --module services/auth --file services/auth/handler.py
python spec_registry.py set-status --id SPEC-001 --status Completed
python spec_registry.py sync
python spec_registry.py status [--task-id TASK-A] [--format json]
python spec_registry.py check  --module services/order [--task-id TASK-B] [--all] [--json]
python spec_registry.py attach --spec SPEC-001 [--base main]
python spec_registry.py check-scope --spec SPEC-001 --base main [--strict] [--json]
python spec_registry.py finish --epic auth --base main
python spec_registry.py worktrees
python spec_registry.py heartbeat --spec SPEC-001 --focus "Implementing JWT" --tool codex
python spec_registry.py heartbeats [--json]
python spec_registry.py watch [--interval 5]
```

## SPEC 文件格式

```markdown
---
id: SPEC-001
title: "JWT authentication middleware"
task_id: "TASK-A"
epic_id: "auth-refactor"
status: "Draft"
owner: "Agent A"
created_at: "2026-08-24"
updated_at: "2026-08-24"
depends_on: []
blocks: []
impact_scope:
  modules:
    - "services/auth"
  files:
    - "services/auth/handler.py"
    - "services/auth/token.py"
  api_endpoints:
    - "POST /api/v1/auth/login"
  db_entities: []
summary: "Add JWT middleware with refresh token support"
breaking_changes: false
---

（SPEC 正文...）
```

**status 合法值**：`Draft` | `In-Progress` | `Completed` | `Deprecated`

**命名规则**：只支持 `SPEC-NNN.md`（例如 `SPEC-001.md`）。带 slug 的名称（如 `SPEC-001-auth.md`）会被 scan 静默跳过。

## 解释规则

- `In-Progress` 的 impact_scope 是意图声明，不是文件所有权保证；冲突要早暴露
- `Completed` 的 scope 是当前基线；影响相同契约时读完整 SPEC 文件
- `blocks` / `depends_on` 必须对称；不对称时 `sync` 发出 WARNING
- 同一 Epic 内的 In-Progress SPEC 不能有 scope_files 重叠；`attach` 会拒绝
- `registry.json` 和 `SPEC-OVERVIEW.md` 出现 git merge 冲突时，丢弃任意一侧后重跑 `sync`，绝不手工合并

## MCP 集成（Claude Code / Cursor / Windsurf）

```bash
pip install mcp
```

在工具配置中注册为 stdio MCP server：

```json
{
  "mcpServers": {
    "spec-registry": {
      "command": "python",
      "args": ["<skill-folder>/scripts/mcp_server.py"]
    }
  }
}
```

暴露四个工具：`spec_create` · `workspace_attach` · `scope_verify` · `state_publish`

## 文件结构

```
spec-registry/
├── SKILL.md
└── scripts/
    ├── spec_registry.py    ← 主 CLI
    └── mcp_server.py       ← MCP 适配层
```
