# **多任务SPEC协同管理方案**

[https://gemini.google.com/app/e82ac93051e5ef66](https://gemini.google.com/app/e82ac93051e5ef66)

*User prompt: 我在同一个项目下有多个任务，每个任务的开发范围不同。它们会各自发SPEC进行代码开发和修复。比如A任务发出了SPEC-1，B任务稍后发出了SPEC-2，随着时间增长，每个任务的发出和完成的SPEC数量很多，为了让每个任务都知道其他任务发出和完成的SPEC，能够对项目有一个全面了解。我应该怎么处理？请给我一个最合理的方案*

Response: 在多任务并发演进、SPEC 频繁发布的场景下，最合理的方案是建立“中心化元数据账本（Spec Registry）+ 变更广播钩子（Change Hook）+ 轻量上下文注入（Context Injection）”的治理机制。

核心目标是：**解耦 SPEC 的详细实现，统一 SPEC 的元数据与生命周期状态**，让任意任务/Agent 在启动或发版时以极低成本获取全局拓扑。

### **1\. 方案核心架构：三层协同机制**

`[ 任务 A ] ──发出 SPEC-01──┐`  
                           `▼`  
`[ 任务 B ] ──完成 SPEC-02──┼──> 【.specs/ 集中注册表】 ──> 【全局上下文/快照】 ──> 注入所有任务`  
                           `▲    (元数据 + 影响范围)       (LLM Context / 仪表盘)`  
`[ 任务 C ] ──进行中 SPEC-03─┘`

#### **① 规范化目录结构与元数据（单点事实来源）**

在代码仓库根目录建立统一的 SPEC 注册中心，每个 SPEC 包含结构化的 Frontmatter 元数据：

`.specs/`  
`├── registry.json             # 机器可读的全局索引（状态机汇总）`  
`├── SPEC-001-auth-jwt.md`  
`├── SPEC-002-order-status.md`  
`└── ...`

每个 SPEC 头部必须包含标准化元数据：

`---`  
`id: SPEC-002`  
`task: Task-B (Order Service)`  
`status: In-Progress # Draft | In-Progress | Completed | Deprecated`  
`depends_on: [SPEC-001]`  
`impact_scope:`  
  `modules: [services/order, api/v1/endpoints]`  
  `db_tables: [orders, order_items]`  
`summary: "重构订单状态流转，增加取消超时自动释放库存逻辑"`  
`---`

### **2\. 状态流转与自动化同步机制**

| 阶段 | 动作 | 自动化触发 | 全局感知效果 |
| :---- | :---- | :---- | :---- |
| **创建 SPEC** | 分支创建 SPEC-xxx.md | CI/Hook 更新 registry.json，标记状态为 Draft/In-Progress | 其他任务拉取最新代码时立即知道“**谁正在改什么模块**”，避免重复劳动或接口冲突。 |
| **开发中** | 任务执行并引用依赖 | 任务初始化时读取 registry.json 中同模块的 SPEC | 编码前自动校验是否有潜在的文件/契约冲突。 |
| **完成 SPEC** | PR 合并 / 任务交付 | 状态变更为 Completed，自动归档变更日志 | 形成版本变更快照，其他任务感知到基线已更新。 |

### **3\. 上下文注入（针对 AI Agent / 开发者）**

为了防止 SPEC 过多导致上下文爆炸，采用“分层摘要（Hierarchy Summaries）”而非全量读取：

> 1. **全局看板注入（L0 级 \- 常驻）**： 在系统 Prompt 或项目根目录维护一个自更新的 SPEC\_OVERVIEW.md（仅列出 ID、状态、负责任务、核心影响模块与一句话描述）。  
> 2. **按需深度加载（L1 级 \- 动态检索）**： 当任务 A 发现自己的修改涉及 db\_tables: \[orders\] 时，再定向读取涉及该表的历史与在办 SPEC 详情。

### **4\. 实施落地步骤**

> 1. **制定 SPEC 模板**：强制要求标明 impact\_scope（修改的文件/模块/数据模型）和 depends\_on。  
> 2. **配置 Git Pre-commit 或 CI Action**：  
   * 扫描 .specs/SPEC-\*.md 自动聚合生成 registry.json 与 SPEC\_OVERVIEW.md。  
> 3. **任务前置检查协议**：  
   * 任何新任务在发出 SPEC 前，必须先读取 registry.json 进行冲突比对（Conflict Detection）。

---

*User prompt: 请提供一套标准化的 SPEC Markdown 模板和元数据定义规范，包含影响范围与依赖声明。*

Response: 统一的 SPEC 文档采用 **YAML Frontmatter（机器可解析）+ 标准 Markdown 结构（人类/LLM 可读）** 的双层设计。

### **SPEC 元数据定义规范**

| 字段 | 类型 | 必填 | 说明 / 取值范围 |
| :---- | :---- | :---- | :---- |
| id | String | 是 | 唯一编号，格式为 SPEC-XXX（如 SPEC-042） |
| title | String | 是 | 简短描述性标题 |
| task\_id | String | 是 | 发出该 SPEC 的任务/分支标识（如 TASK-AUTH-01） |
| status | String | 是 | Draft（草稿）、In-Progress（开发中）、Completed（已完成）、Deprecated（已废弃） |
| owner | String | 是 | 负责人、Agent 角色或任务名 |
| created\_at | Date | 是 | 创建日期（YYYY-MM-DD） |
| updated\_at | Date | 是 | 最新更新日期（YYYY-MM-DD） |
| depends\_on | Array | 否 | 显式依赖的前置 SPEC 列表（如 \[SPEC-001, SPEC-012\]） |
| blocks | Array | 否 | 声明该 SPEC 会阻塞的其他任务/SPEC |
| impact\_scope | Object | 是 | 声明影响范围，细分为 modules、files、api\_endpoints、db\_entities |

### **标准 Markdown 模板 (.specs/SPEC-TEMPLATE.md)**

`---`  
`id: SPEC-000`  
`title: "简明扼要的特性/修复名称"`  
`task_id: "TASK-XXX"`  
`status: "Draft" # Draft | In-Progress | Completed | Deprecated`  
`owner: "Dev-Name / Agent-Role"`  
`created_at: "2026-08-23"`  
`updated_at: "2026-08-23"`  
`depends_on:`  
  `- "SPEC-001"`  
`blocks: []`  
`impact_scope:`  
  `modules:`  
    `- "services/order"`  
    `- "pkg/middleware"`  
  `files:`  
    `- "services/order/handler.go"`  
    `- "pkg/middleware/auth.go"`  
  `api_endpoints:`  
    `- "POST /api/v1/orders"`  
    `- "GET /api/v1/orders/{id}"`  
  `db_entities:`  
    `- "table: orders"`  
    `- "field: orders.status"`  
`---`

`**背景与动机 (Context & Motivation)**`  
`简述为什么发出此 SPEC，要解决什么问题或支持什么业务场景。`

`**核心变更设计 (Technical Design)**`  
`* **数据流/模型变更**：核心数据结构、数据库 Schema 变更或 DTO 调整。`  
`* **接口契约定义**：新增或变更的 API Request/Response 结构。`  
`* **处理逻辑**：核心算法、状态转移或时序处理逻辑。`

`**依赖与下游影响 (Dependencies & Side Effects)**`  
`* **前置依赖**：执行本 SPEC 前需确保哪些 SPEC/契约已就绪。`  
`* **破坏性变更 (Breaking Changes)**：是否存在下游兼容性风险（如字段废弃、接口路径变动）。若有，下游任务如何平滑适配。`

`**验收标准 (Acceptance Criteria)**`  
`* [ ] 关键测试用例或自动化测试覆盖。`  
`* [ ] 接口契约测试通过。`  
`* [ ] 相关迁移脚本（Migration）已验证。`

### **全局注册表示例 (.specs/registry.json)**

解析上述 SPEC 后自动聚合生成的全局索引，供其他任务在启动时快速检索：

`{`  
  `"last_updated": "2026-08-23T10:00:00Z",`  
  `"specs": [`  
    `{`  
      `"id": "SPEC-002",`  
      `"title": "订单超时自动取消机制",`  
      `"task_id": "TASK-ORDER-02",`  
      `"status": "In-Progress",`  
      `"owner": "Backend-Agent",`  
      `"depends_on": ["SPEC-001"],`  
      `"impact_scope": {`  
        `"modules": ["services/order"],`  
        `"files": ["services/order/handler.go"],`  
        `"api_endpoints": ["POST /api/v1/orders"],`  
        `"db_entities": ["table: orders"]`  
      `}`  
    `}`  
  `]`  
`}`

每个并发任务在编写新 SPEC 或启动代码开发前，通过匹配 registry.json 中的 impact\_scope，即可在秒级发现同模块是否存在并发修改冲突。

---

*User prompt: 以上问题是一个项目开发和管理的常见情况么？*

Response: 是的，这不仅是项目开发中的**高频常见问题**，更是软件工程协同和项目管理中最核心的痛点之一。

无论是在**传统多团队协作**，还是在当前的**多 Agent 并发开发 / AI 辅助编程**场景下，这类问题都会随着并行任务数量的增长而呈指数级放大。

### **1\. 传统工程与项目管理中的对应形态**

在没有 AI 的传统研发场景中，这个问题通常以以下形式出现：

> * **技术设计割裂（Design Silos）**：团队 A 在做“用户权限改造”，团队 B 在做“订单结算重构”，由于缺乏统一的设计元数据共享，双方直到联调或提 PR 时才发现数据模型或公共中间件被改坏了。  
> * **架构决策记录缺失（ADR 痛点）**：项目演化几个月后，没人知道某个字段或接口为什么被改动，新任务很容易推翻前人已经验证过的方案。  
> * **接口与依赖地狱（Contract Drift）**：各任务自顾自地定义 API，缺少统一的契约管理，导致破坏性变更（Breaking Change）频发。

### **2\. 为什么在 AI / 多任务并行时代更严重？**

随着单项目下拆分出多个并行任务（例如多个 Subagent、自动化流水线或多分支并发作业），这个问题被显著放大了：

| 维度 | 传统人工团队 | 并发任务 / Multi-Agent 场景 |
| :---- | :---- | :---- |
| **产出速度** | 几天/几周产出一个 SPEC | 几分钟到几小时产出一个 SPEC |
| **沟通方式** | 站会、架构评审会、即时通讯 | 依赖上下文注入、文件协议与索引 |
| **上下文窗口** | 人的记忆模糊但有常识补偿 | 上下文长度有限，全量读取历史 SPEC 会爆 Token |
| **冲突成本** | 代码合并冲突人工解决 | 容易导致 Agent 产生幻觉、覆盖代码或破坏基线 |

### **3\. 业界的成熟应对标准**

你所面临的这种管理需求，在成熟软件工程中有明确的标准实践支撑：

> * **ADR（Architecture Decision Records，架构决策记录）**：将关键技术设计以轻量 Markdown 格式保存在代码库（如 doc/adr/），作为项目的唯一架构事实来源。  
> * **Schema-First / Contract-Driven（契约驱动开发）**：通过 OpenAPI、Protobuf 等机器可读的元数据先行定义接口，再并行开发。  
> * **基于拓扑依赖的 CI 门禁**：通过扫描影响范围（Impact Analysis），在任务合并或执行前自动拦截依赖未就绪或存在冲突的变更。

因此，为你当前的项目建立 **SPEC 集中注册表与影响范围声明**，不仅是解决当前信息孤岛的必要手段，也是保证多任务并发演进时系统架构不失控的行业标准解法。

---

*User prompt: 为什么这些AI厂商的桌面版应用程序，不然agy没有一个功能来处理呢？*

Response: 这类工具（包括 Google Antigravity、Cursor、Windsurf 等）目前没有提供开箱即用的“多 SPEC 跨任务自动协调与注册中心”功能，主要受限于**产品演进阶段、工程哲学差异以及上下文架构的权衡**：

### **1\. 工具当前聚焦于“执行层”，而非“治理层”**

目前主流 AI 桌面端产品的核心发力点在于：

> * **单任务端到端闭环**：如何让一个 Agent 自主完成编写、运行测试、浏览器调试（Browser Agent）和生成 Artifacts（Diff、计划）。  
> * **并行工作流基础支撑**：提供 Manager View、Parallel Subagents、Worktree 隔离等能力，实现多任务物理并发。

简而言之，厂商当前主要在解决“如何让 5 个 Agent 同时干活不卡顿”**（Execution Fabric），还没来得及深入解决**“5 个 Agent 干活时如何协商业务与架构契约”（Governance & Orchestration）。

### **2\. “文件即契约”的架构哲学（Decoupling via Repo）**

IDE 厂商倾向于遵循类似 Git 的设计原则：**工具提供执行载体，流程规范留在仓库内。**

> * **防止流程锁定**：不同团队的 SPEC 格式千差万别（有的用 PRD、有的用 RFC、有的用 ADR 或 OpenAPI）。如果平台硬编码一套 SPEC 规范，会限制灵活性。  
> * **仓库才是单一事实来源（Single Source of Truth）**：像 Antigravity 支持在 .agent/、.rules 或自定义 Markdown 中定义角色与工作流，目的是让开发者通过标准化文件协议来组织项目，使协作逻辑随代码仓库版本化流转。

### **3\. 上下文窗口与 Token 经济学瓶颈**

如果工具默认将所有任务的历史与在办 SPEC 自动同步给每个 Agent：

> * **上下文爆炸（Context Bloat）**：当项目积累了 50 个 SPEC，每次触发任务都全量广播，不仅响应延迟倍增、费用剧增，还会冲淡核心 Prompt。  
> * **注意力干扰（Attention Dilution）**：模型在吸收过多与当前任务无关的 SPEC 时，更容易产生幻觉或过度泛化。

因此，平台目前将“哪些 SPEC 该被读取”的裁剪控制权交给了开发者（通过检索或显式引用）。

### **当前最优的桥接方案**

虽然客户端没有内置这一 UI 功能，但可以利用平台现有的扩展机制自建低成本闭环：

> 1. **利用 Custom Rules / Agent Instructions 固化协议**： 在全局规则或 Agent 设定中加入一条铁律：*“在执行任何改动前，先检索 .specs/registry.json，声明当前任务的 impact\_scope 并检查依赖。”*  
> 2. **利用 Lifecycle Hooks / Workflows 自动化注册**： 配置 pre-task / post-task 钩子脚本，在 Agent 生成或完成 SPEC 时，自动运行解析脚本更新注册表。

**Sources**

> 1. [Overview | Google Antigravity Docs](https://antigravity.google/docs/ide/overview/)  
> 2. [Workflows | Google Antigravity Docs](https://antigravity.google/docs/ide/workflows)

---

*User prompt: 这个问题和worktree是否在结构上有相似之处？都是同一项目下的多任务管理问题？能否进行统一处理？*

Response: **完全相通**。你的直觉非常精准。

git worktree 和 SPEC 多任务管理本质上是**同一枚硬币的两面**——一个是**物理文件层**的多任务隔离，另一个是**逻辑语义/契约层**的多任务隔离。它们完全可以、也应当进行**统一绑定处理**。

### **1\. 结构上的映射关系**

| 维度 | git worktree (物理/文件层) | SPEC 管理 (语义/契约层) |
| :---- | :---- | :---- |
| **隔离单元** | 独立的工作目录与分支 (Branch) | 独立的 SPEC-XXX.md |
| **生命周期** | 创建分支 → 编码调试 → 合并主分支 | Draft → In-Progress → Completed |
| **冲突表现** | Git Merge Conflict（文件行级别冲突） | Contract Drift / 架构破坏（逻辑/API 级别冲突） |
| **解决痛点** | 避免切分支时暂存、重装依赖的物理污染 | 避免多任务并发时接口与数据模型的设计打架 |

### **2\. 统一处理模型：1 Worktree \= 1 Task Branch \= 1 SPEC**

不要将 SPEC 和 Worktree 割裂维护，直接建立“一一映射”的闭环流水线：

`[任务发起]`  
   `│`  
   `▼`  
`1. 创建 Worktree & 分支 (task/SPEC-042)`  
   `│`  
   `▼`  
`2. 初始化并提交 .specs/SPEC-042.md (状态: In-Progress)`  
   `│`  
   `▼`  
`3. 触发自动化脚本 ──> 聚合所有 Active Worktree 的 SPEC ──> 刷新 registry.json`  
   `│`  
   `▼`  
`4. 开发与测试 (当前 Agent 仅挂载自身 Worktree，读取统一生成的 registry.json 避免冲突)`  
   `│`  
   `▼`  
`5. 任务交付 ──> PR 合并至主干 (状态变更为 Completed) ──> 清理 Worktree`

### **3\. 统一落地实践方案**

利用 Git 的内置机制（Hooks / 脚本）将 Worktree 状态与 SPEC 状态自动化绑定：

**① 统一命名契约**

> * **Worktree 路径**：.worktrees/SPEC-042-order-cancel  
> * **Git 分支名**：feat/SPEC-042  
> * **SPEC 文件**：.specs/SPEC-042.md

**② 自动化聚合脚本 (scripts/sync-specs.sh)** 写一个轻量脚本，在任务切换或 CI 构建时执行：

> 1. 扫描当前仓库所有未合并的 Worktree 分支。  
> 2. 提取每个分支下的 SPEC-XXX.md 头部元数据。  
> 3. 动态聚合出全项目的活动视图 registry.json 和 ACTIVE\_TASKS.md。

**③ 收益**

> * **零上下文膨胀**：每个 Worktree 只包含该任务需要的实际改动代码，Agent 工作区极度干净。  
> * **物理 \+ 语义双保险**：在物理层用 Worktree 隔绝脏读，在语义层通过 registry.json 中的 impact\_scope 提前预警并发改动冲突。

---

*User prompt: 如果一对一，会导致worktree的数量快速增长，因为SPEC很多，是否会加重项目管理的复杂性？*

Response: 如果**每个 SPEC 都长期保留一个 Worktree**，确实会导致磁盘占用爆炸、分支泛滥，显著加重物理管理成本。

解决这一复杂性的关键在于区分“静态资产”**与**“瞬态运行时”：

> * **SPEC 是静态资产（永久保留）**：记录设计决策与历史，只占用几 KB 文本，随 Git 历史永久存档。  
> * **Worktree 是瞬态运行时（即用即销）**：只作为**并发执行中的沙箱**，任务结束（合并后）必须立即销毁。

### **1\. 控制复杂性的核心机制：生命周期脱钩与限流**

`SPEC 数量（持续累加：1 → 50 → 200） ── 归档在 .specs/ 目录（极轻量）`  
                 `│`  
                 `▼ 过滤：仅对状态为 In-Progress 的任务创建运行时`  
`Worktree 数量（动态受限：常驻 2 ~ 5 个） ── 任务完成后 prune 销毁`

> * **严格的配额上限（Concurrency Cap）**：任何时刻本地活跃的 Worktree 数量控制在 **3～5 个以内**（对应当前正在并行推进的活跃任务数）。  
> * **自动化清理策略（Lifecycle Hook）**：  
  * **创建**：任务进入 In-Progress 时动态挂载 Worktree。  
  * **销毁**：任务完成、SPEC 变为 Completed 并合并到主干后，触发 git worktree remove，物理空间瞬间释放。

### **2\. 避免 Worktree 泛滥的两种实战模式**

根据团队/任务的并发粒度，通常有两种优化模式：

#### **模式 A：任务级 Worktree，粒度聚合（推荐）**

不要为每一个细小的 Bugfix SPEC 都开一个 Worktree，而是按“Epic / 功能模块”分配 Worktree：

> * 一个 Worktree（例如 feature/order-refactor）内可以顺序推进 SPEC-011（数据表改造）和 SPEC-012（API 实现）。  
> * 粒度较大的特性才独占 Worktree，微小修复直接在主工作区或轻量分支解决。

#### **模式 B：瞬态沙箱（Ephemeral Worktree）**

将 Worktree 视为临时编译容器：

> * 编写 SPEC 元数据时直接在主分支提交（仅改动 .specs/，无代码冲突风险）。  
> * 只有当 Agent 需要**编译、跑测试、多分支并行改代码**时，脚本才临时生成 Worktree；测试通过合并回主干后，脚本自动执行清理。

### **3\. 轻量维护指令**

通过简单的别名或脚本，将 Worktree 的维护成本降至接近零：

> * **清理已完成/失效的 Worktree**：  
>   `git worktree prune`

> * **一键列出当前活跃任务状态**：  
>   `git worktree list`

> * **结论**：SPEC 的增长不会导致管理失控，因为膨胀的只是文本索引；只要坚持“Active 时挂载、Merged 时销毁”的瞬态原则，本地 Worktree 永远只保持在极少数活跃并发状态。

---

*User prompt: 不要为每一个细小的 Bugfix SPEC 都开一个 Worktree，而是按“Epic / 功能模块”分配 Worktree？ 现在我们都是通过AI进行vibing coding，怎么让agent来遵守这个规则？如果一个项目是多个agent协同开发（A 设计，B开发，C审核），怎么让它们统一执行这个纪律？*

Response: 在 AI Vibe Coding 和多 Agent 协同场景下，**绝对不能寄希望于 Agent 的“自觉性”或泛化 Prompt**。大模型在上下文漂移时极易随意创建分支或胡乱改动文件。

要让多个 Agent（A 设计、B 开发、C 审核）严格遵守“按 Epic 复用 Worktree”的纪律，核心是“护栏工程（Harness Engineering）+ 状态机工具化”：把规则封装成确定性脚本，把任意 Git 操作降级为固定的命令调用。

### **1\. 确定性工具封装：剥夺 Agent 随意建 Worktree 的自由**

不要让 Agent 自主执行 git worktree add，而是提供统一的脚手架 CLI（例如 .scripts/workspace.sh），将 Worktree 的生命周期锁死在 Epic 维度。

`# 1. 启动/关联 Epic（若已有则复用，无则自动创建 worktree）`  
`./scripts/workspace.sh attach --epic "order-refactor" --spec "SPEC-012"`

`# 2. 提交审查并流转状态`  
`./scripts/workspace.sh submit --spec "SPEC-012"`

`# 3. 审核通过合并并释放环境`  
`./scripts/workspace.sh finish --epic "order-refactor"`

> * **底层逻辑**：脚本内部自动维护 Epic \<-\> Worktree \<-\> Specs\[\] 的映射表。无论 Agent 发出多少个小 Bugfix SPEC，只要所属 Epic 相同，脚本自动将其路由至同一个已存在的 Worktree 目录，从物理机制上阻断 Worktree 膨胀。

### **2\. 多 Agent 职责分工与状态流转**

将流水线拆解为不可越权的三方分工，通过文件和状态流转驱动协同：

| 角色 | 核心动作 | 触碰范围 | 规则约束 |
| :---- | :---- | :---- | :---- |
| **Agent A (架构/设计)** | 编写/拆解 SPEC，评估影响范围，指定归属 epic\_id。 | 仅主分支的 .specs/ 目录 | **禁止写业务代码**；新 SPEC 必须挂靠在已有 Epic 或声明开启新 Epic。 |
| **Agent B (开发/实现)** | 读取 SPEC，执行 attach 脚本进入指定 Worktree 开发并写测试。 | 仅限指定 Worktree 内部 | **禁止自建 Worktree**；只改动 SPEC 声明的 impact\_scope 范围内的文件。 |
| **Agent C (审核/门禁)** | 校验代码 Diff 是否超出 impact\_scope，跑测试套件，执行 finish。 | 审核 Diff，执行 Merge & Prune | 存在未声明的文件变动直接拒绝；确认所有关联 SPEC 完成后执行物理 Worktree 销毁。 |

### **3\. Agent 规则文件配置 (Prompt/Rule 级约束)**

在项目全局规则（如 .agent/rules 或 System Instructions）中注入硬性 SOP：

`# Multi-Agent Workflow Invariants`

`1. [Architect Agent]`  
   ``- Generate SPEC in `.specs/SPEC-XXX.md`.``  
   ``- Must specify `epic_id` in metadata. Do NOT create code branches.``

`2. [Developer Agent]`  
   ``- NEVER run `git worktree add` or `git checkout -b` directly.``  
   ``- ALWAYS run `./scripts/workspace.sh attach --epic <epic_id> --spec <id>`.``  
   `- All code edits MUST take place inside the returned worktree path.`  
   ``- Modifying files outside the declared `impact_scope` is strictly prohibited.``

`3. [Reviewer Agent]`  
   ``- Validate that git diff matches `.specs/SPEC-XXX.md` `impact_scope`.``  
   ``- On pass: trigger `./scripts/workspace.sh finish --epic <epic_id>`.``

### **4\. 自动化硬门禁（CI / Git Hook 拦截）**

在 Git pre-commit 或 CI 中加入自动校验脚本：

> * **超范围拦截**：比对当前分支的改动文件列表与当前 SPEC 的 impact\_scope，一旦出现未报备文件的修改，直接阻断 Commit。  
> * **分支孤儿拦截**：如果检测到没有挂载合法 SPEC/Epic 元数据的分支与 Worktree，CI 直接报错阻断合并。

通过“脚本管物理环境、SPEC 管逻辑契约、Reviewer 管合规门禁”，即使是 10 个 Agent 高频并发，也能保证整个系统的 Worktree 数量恒定在极低水平，架构演进井然有序。

---

*User prompt: 好的，提供一份现成的 workspace.sh 脚本实现方案，要包含以上worktree & SPEC适配问题的解决方法*

Response: Your workspace.sh script is ready:

\[file-tag: code-generated-file-e623152c-244c-42d2-a716-f40dc29bb1be\]

### **workspace.sh 核心设计与解决思路**

本脚本专为 **“按 Epic 聚合 Worktree \+ SPEC 状态机管理 \+ Agent 护栏拦截”** 设计，彻底解决了 Worktree 泛滥和 Agent 越权改动代码的问题。

                        `┌──────────────┐`  
                        `│ Agent A (架构)│`  
                        `└──────┬───────┘`  
                               `│ 1. new-spec (--epic order --id SPEC-012)`  
                               `▼`  
     `┌──────────────────────────────────────────────────┐`  
     `│ 集中元数据层 (.specs/registry.json & 看板)        │`  
     `└─────────────────────────┬────────────────────────┘`  
                               `│ 2. attach (--epic order --spec SPEC-012)`  
                               `▼`  
                        `┌──────────────┐`  
                        `│ Agent B (开发)│ ── 在 .worktrees/epic-order/ 独立沙箱编码`  
                        `└──────┬───────┘`  
                               `│ 3. check-scope (--spec SPEC-012) 护栏校验`  
                               `▼`  
                        `┌──────────────┐`  
                        `│ Agent C (审核)│`  
                        `└──────┬───────┘`  
                               `│ 4. finish (--epic order)`  
                               `▼`  
        `[合并分支 -> SPEC 置为 Completed -> 物理销毁 Worktree & Prune]`

### **1\. 核心命令与用法**

| 命令 | 适用角色 | 核心行为 |
| :---- | :---- | :---- |
| new-spec | **Agent A (架构)** | 创建带 YAML Frontmatter 的 SPEC 模板，自动关联所属 epic，刷新全局看板。 |
| attach | **Agent B (开发)** | 检查当前 Epic 是否已有 Worktree。**有则复用，无则自动创建**；将 SPEC 状态置为 In-Progress。 |
| check-scope | **Agent C (审核/门禁)** | 自动比对 Git Diff 与 SPEC 中声明的 impact\_scope。**一旦发现修改了未报备的文件，直接拦截报错**。 |
| finish | **Agent C (审核/完成)** | 将该 Epic 下的所有 SPEC 标记为 Completed，**自动删除并 prune 物理 Worktree**，释放磁盘空间。 |
| sync / status | **所有 Agent** | 重新解析所有 .specs/SPEC-\*.md，聚合生成机器友好的 registry.json 与人类/LLM 友好的 ACTIVE\_TASKS.md。 |

### **2\. 跨 Agent 落地协同 SOP**

在项目的 Prompt 或 Agent Instructions（如 .agent/rules）中直接配置以下规则：

#### **① 架构 Agent (Agent A) 规则**

`- 禁止直接改动业务代码。`  
`- 发起新任务时必须运行：`  
  `` `./scripts/workspace.sh new-spec --id SPEC-042 --epic <epic_name> --title "<简述>"` ``  
``- 必须在生成的 `.specs/SPEC-042.md` 中补齐 `impact_scope.files` 与依赖声明。``

#### **② 编码 Agent (Agent B) 规则**

``- 禁止自行执行 `git checkout -b` 或 `git worktree add`。``  
`- 接单时运行：`  
  `` `./scripts/workspace.sh attach --epic <epic_name> --spec SPEC-042` ``  
``- 严格在终端提示的 `.worktrees/epic-<epic_name>/` 目录内编码，禁止修改 `impact_scope` 以外的文件。``

#### **③ 审核/门禁 Agent (Agent C) 规则**

`- 验证代码前必须运行范围校验：`  
  `` `./scripts/workspace.sh check-scope --spec SPEC-042` ``  
`- 校验通过、测试通过并合并后，运行收尾清理：`  
  `` `./scripts/workspace.sh finish --epic <epic_name>` ``

### **3\. 安装与快速使用**

> 1. 将 workspace.sh 保存至项目的 scripts/ 目录：  
>    `mkdir -p scripts`  
>    `mv workspace.sh scripts/`  
>    `chmod +x scripts/workspace.sh`

> 2. 执行初始化状态扫描：  
>    `./scripts/workspace.sh sync`

> 3. 查看当前全局任务视图：  
>    `./scripts/workspace.sh status`

---

*User prompt: 再确认下，每个任务 、worktree是否都是独立上下文空间？*

Response: **是的**。在架构设计中，每个任务和 Worktree 在“物理运行环境”**和**“Agent 认知会话”**两个维度上都是**严格独立的上下文空间，唯独通过“极轻量的全局元数据”进行单向联通。

### **1\. 双重隔离模型**

| 维度 | 隔离状态 | 具体表现与隔离边界 |
| :---- | :---- | :---- |
| **物理文件 / 运行上下文** *(Git Worktree)* | **完全独立** | \* 独立的文件目录与分支 HEAD，互不干扰。 \* 独立的编译产物、依赖缓存（如 node\_modules / target）与测试运行时。 \* 任务 A 的未提交代码（Uncommitted Changes）对任务 B 绝对不可见，杜绝物理脏读。 |
| **模型认知 / Token 会话上下文** *(Agent Session)* | **完全独立** | \* 每个 Agent 拥有独立的对话历史、推理链（Scratchpad）与系统提示词。 \* Agent 在自身 Worktree 内建立本地代码索引（Codebase Embedding），不会读入其他分支的未合并脏代码。 \* 杜绝了多任务混合导致的上下文爆炸（Context Bloat）与注意力漂移。 |

### **2\. 隔离之下的“唯一桥梁”：元数据广播**

为了避免“完全隔离”导致各个任务变成信息孤岛，两个上下文空间之间**只保留唯一的通信桥梁**：

`[ Task A 独立上下文 ]                [ Task B 独立上下文 ]`  
 `├─ Worktree: epic-order/             ├─ Worktree: epic-auth/`  
 `└─ Agent: Order Session              └─ Agent: Auth Session`  
          `│                                    │`  
          `│ 仅同步 1-2KB 元数据                 │ 仅读取 1-2KB 看板`  
          `▼                                    ▼`  
    `┌─────────────────────────────────────────────────┐`  
    `│ 共享事实来源: .specs/registry.json & 看板文件    │`  
    `│ (声明: 我要改 orders 表，占用 /api/v1/orders)   │`  
    `└─────────────────────────────────────────────────┘`

> * **不共享的内容**：不共享彼此的对话历史、不共享未提交的代码细节、不共享繁杂的中间推理过程。  
> * **唯一共享的内容**：只共享 ACTIVE\_TASKS.md / registry.json 中**一句话概述、影响文件清单（impact\_scope）与当前状态**。

### **3\. 这种设计的直接收益**

> 1. **零污染并发**：Agent B 可以放心运行全量测试或执行 git reset，绝不会影响 Agent A 正在跑的调试服务。  
> 2. **极低 Token 消耗**：每个 Agent 只需要关注自己当前模块的 200 行代码，同时只需花费几十个 Token 扫一眼全局注册表确认没有模块冲突。  
> 3. **确定性审计**：出现问题时，每个任务的执行记录（Git Diff \+ SPEC 文档）边界清晰，回滚或交接极为简单。

---

*User prompt: 请仔细阅读这2个文档，内容这是你之前上传github仓库的跨agent跨会话的skill，这个架构和功能是否也和以上问题相似？如果可行，是否可以全部进行统一？*

Response: **完全可行，而且这两者结合正是构建完整的 AI 智能体治理工程（Harness Engineering）的“最后一块拼图”。**

你之前设计的 ai-agent-skills（UAS 状态格式、文件总线 .sync/、Relay/Concurrent 模式）与我们刚刚讨论的 SPEC \+ Worktree 方案，不仅在结构上完全同构，而且恰好分别覆盖了“静态契约治理”**与**“动态运行时感知”。

将它们合二为一，就能形成一套**从架构设计、物理沙箱隔离，到跨工具/跨会话实时感知、断点续跑的完整闭环体系**。

### **一、 架构同构性与互补性分析**

这两套体系在维度上是**精准互补**的：

`┌─────────────────────────────────────────────────────────────────────────┐`  
`│                      统一的 AI 协同治理体系                                │`  
`├──────────────────────────┬──────────────────────────────────────────────┤`  
`│ 刚才讨论的 SPEC + Worktree│ 你仓库中的 ai-agent-skills (UAS / .sync)      │`  
`├──────────────────────────┼──────────────────────────────────────────────┤`  
`│ 解决「改什么」与「在哪改」 │ 解决「谁在改」、「改到哪了」与「会话接力」     │`  
`│ 静态/契约维度 (Contract)  │ 动态/心跳维度 (Runtime Heartbeat)            │`  
`│ 粒度：Epic / 模块 / 文件 │ 粒度：Session / Context / 阻塞点 / 决策记录  │`  
`│ 存储：.specs/ + .worktrees│ 存储：.sync/ (task_x.json) + MERGED_STATE.md │`  
`└──────────────────────────┴──────────────────────────────────────────────┘`

#### **为什么说它们能完美统一？**

> 1. **通信介质完全一致（文件即总线）**：  
   * 两者都遵循“代码仓库是唯一事实来源”的哲学，不需要引入复杂的外部数据库或重量级平台，全部采用 **轻量 Markdown \+ JSON \+ 文件监听（fswatch/inotify/python）** 实现。  
> 2. **任务标识天然对齐**：  
   * ai-agent-skills 中的 task\_id（如 feature-auth），可以直接与 SPEC 的 id（SPEC-012）和 epic（epic-order）做映射绑定。  
> 3. **Relay 模式完美解决 Worktree 内的上下文耗尽问题**：  
   * 当开发 Agent（如 Gemini）在某个 Worktree 内写到 80% 突然爆 Token 或额度用尽时，触发 ai-agent-skills 的 **Relay (Handoff)** 机制，将断点写入 .sync/，GLM/Claude 直接进入**同一个 Worktree** 无缝接盘，无需重新构建物理环境。

### **二、 终极统一模型：三层全栈协同架构**

统一后的系统分为清晰的三层，所有 Agent（Claude Code、ZCode、Cursor、Windsurf）都基于同一套底层资产协作：

`[ 顶层：Agent 认知层 ]     Agent A (架构)       Agent B (开发)        Agent C (审核)`  
                               `│                    │                    │`  
                               `▼                    ▼                    ▼`  
`[ L3: 动态运行时感知层 ]   ┌────────────────────────────────────────────────────┐`  
  `(ai-agent-skills)        │  .sync/task-*.json (UAS 心跳) ──> MERGED_STATE.md   │`  
                           `│  - 状态：current_focus, blockers, decisions       │`  
                           `│  - 模式：Concurrent(并发感知) / Relay(接力断点)     │`  
                           `└────────────────────────┬───────────────────────────┘`  
                                                    `│`  
`[ L2: 静态契约与看板层 ]   ┌────────────────────────▼───────────────────────────┐`  
  `(SPEC Registry)          │  .specs/SPEC-*.md  ──> registry.json               │`  
                           `│  - 契约：impact_scope (文件/模块/表), depends_on   │`  
                           `└────────────────────────┬───────────────────────────┘`  
                                                    `│`  
`[ L1: 物理环境隔离层 ]     ┌────────────────────────▼───────────────────────────┐`  
  `(Git Worktrees)          │  .worktrees/epic-<name>/ (独立沙箱运行区)           │`  
                           `│  - 机制：按 Epic 复用，任务完成即 prune 销毁       │`  
                           `└────────────────────────────────────────────────────┘`

### **三、 统一后的全流程协同流水线（SOP）**

在这个统一体系下，多 Agent 的协同过程变得极其平滑：

`1. 架构规划 (Agent A)`  
   `└── 执行: ./scripts/workspace.sh new-spec --id SPEC-042 --epic auth --title "OAuth2实现"`  
   `└── 产物: 写入 .specs/SPEC-042.md (定义 impact_scope)`

`2. 开发认领与物理挂载 (Agent B)`  
   `└── 执行: ./scripts/workspace.sh attach --epic auth --spec SPEC-042`  
   `└── 产物: 挂载进入 .worktrees/epic-auth/，SPEC 状态置为 In-Progress`

`3. 动态心跳广播 (Agent B 编码中)`  
   `└── 机制: 触发 universal-task-sync 写入 .sync/SPEC-042.json (UAS 格式)`  
   `└── 内容: "current_focus: 正在实现 Token 拦截器", "mode: concurrent"`  
   `└── 效果: 聚合出 .sync/MERGED_STATE.md，其他并发 Agent 实时感知其进度与决策！`

`4. 异常接力 (若 Agent B 上下文耗尽)`  
   `└── 机制: 触发 Relay Handoff，生成 sender_continues: false 的 UAS 快照`  
   `└── 效果: Agent B2 (另一工具/模型) 启动，进入同一个 worktree，读入快照 1 秒断点续跑！`

`5. 审核与门禁 (Agent C)`  
   `└── 执行: ./scripts/workspace.sh check-scope --spec SPEC-042`  
   `└── 校验: 比对实际 git diff 与 SPEC impact_scope，杜绝越权改动`  
   `└── 交付: ./scripts/workspace.sh finish --epic auth (合并代码、标记 Completed、销毁 worktree)`

### **四、 统一后的项目目录结构**

把 ai-agent-skills 的同步机制直接内嵌到项目中，形成统一的目录拓扑：

`my-project/`  
`├── .specs/                         # [L2: 静态契约]`  
`│   ├── SPEC-001-auth.md`  
`│   ├── SPEC-002-order.md`  
`│   ├── registry.json               # 机器可读的全局索引`  
`│   └── ACTIVE_TASKS.md             # 静态看板`  
`│`  
`├── .sync/                          # [L3: 动态运行时总线 (UAS)]`  
`│   ├── SPEC-001.json               # 正在运行的 Task/SPEC 动态心跳`  
`│   ├── SPEC-002.json`  
`│   ├── MERGED_STATE.md             # 动态运行态汇总看板 (Watcher 自动维护)`  
`│   └── watcher.pid`  
`│`  
`├── .worktrees/                     # [L1: 物理隔离沙箱 (Git Ignored)]`  
`│   ├── epic-auth/`  
`│   └── epic-order/`  
`│`  
`└── scripts/                        # [统一治理工具集]`  
    `├── workspace.sh                # Worktree 与 SPEC 管理（包含 check-scope）`  
    `├── watcher.sh                  # 状态监听进程（来自 universal-task-sync）`  
    `└── merge-states.py             # UAS 状态聚合脚本`

### **五、 统一后的 UAS（Unified Agent State）扩展定义**

为了让 UAS 与 SPEC 深度融合，只需在标准 UAS 格式中增加 spec\_id 和 epic 字段，实现数据互通：

`{`  
  `"schema_version": "2.0",`  
  `"task_id": "SPEC-042",`  
  `"spec_id": "SPEC-042",`  
  `"epic": "auth-refactor",`  
  `"agent_model": "claude-3-7-sonnet",`  
  `"agent_tool": "claude-code",`  
  `"worktree": ".worktrees/epic-auth-refactor",`  
    
  `"mode": "concurrent",`  
  `"sender_continues": true,`  
  `"timestamp": "2026-08-23T10:00:00+08:00",`  
  `"context_level": 55,`  
    
  `"current_focus": "实现 RefreshToken 轮换机制",`  
  `"completed": [`  
    `"POST /api/v1/auth/login 接口完成",`  
    `"JWT 中间件测试通过"`  
  `],`  
  `"in_progress": [`  
    `"RefreshToken Redis 存储逻辑"`  
  `],`  
  `"blockers": [`  
    `"等待 SPEC-040 的 Redis 配置中间件就绪"`  
  `],`  
  `"key_decisions": [`  
    `"Token 刷新窗口设定为 7 天"`  
  `]`  
`}`

### **六、 总结：统一治理的收益**

> 1. **从“各自为战”到“全景透明”**：  
   * SPEC 层管住了**长期的架构与文件边界**（防止代码冲突、越权修改）；  
   * UAS/.sync 层管住了**短期的开发动作与会话心跳**（防止重复劳动、支持断点交接）。  
> 2. **跨模型/跨工具无缝协作**：  
   * 无论使用的是 Claude Code（借助 MCP/Hooks）还是 ZCode/Cursor/Windsurf（借助文件总线与系统提示词），所有 Agent 看到的都是同一个 MERGED\_STATE.md 和 registry.json。  
> 3. **极简运维**：  
   * 整个体系完全基于 Git 仓库原生文件运作，不需要部署数据库或第三方协同 SaaS，是真正的 **Harness Engineering（智能体脚手架与护栏工程）最佳实践**。

---

*User prompt: 这两者结合正是构建完整的 AI 智能体治理工程（Harness Engineering）的“最后一块拼图”？ 既然这些都是项目开发和管理的通用问题，为什么这么多harness，比如codex, agy, zcode, claude都没有实现以上功能？需要我们自己来处理？*

Response: 各大 AI 工具厂商（Claude Code、Google Antigravity、ZCode 等）没有内置开箱即用的跨任务 SPEC 契约与 Worktree 自动协调机制，主要源于以下四个核心层面的工程与商业考量：

**1\. 机制与策略的分离（Mechanism vs. Policy 哲学）** AI 编程工具厂商遵循经典 Unix 哲学：**提供底层的执行机制（Mechanism），将具体的工程流程（Policy）留给开发者。**

> * 厂商提供的是原子能力：终端交互、文件读写、MCP 协议、Subagent 派生与 Worktree 物理隔离。  
> * 如果厂商在客户端硬编码一套“基于 SPEC \+ Epic Worktree \+ UAS 状态总线”的管理逻辑，就会与企业现有的 Jira、Linear、敏捷看板或 GitFlow 规范产生冲突。它们宁愿做通用的“底座”，让项目按需自建流程。

**2\. 商业壁垒与生态孤岛** 不同厂商之间存在天然的商业竞争：

> * Anthropic 期望用户全流程留在 Claude Code 的 MCP 生态；  
> * 没有哪家商业 IDE 会主动内置一套“当自身模型额度耗尽时，无缝将上下文与 Worktree 交接给竞品模型”的通用接力协议。跨工具、跨模型的无缝同步与 Handoff，只能由开发者在顶层通过中立的文件总线与提示词协议自建。

**3\. “微观单兵执行”与“宏观协同治理”的阶段分工** 目前 AI 厂商的竞争焦点仍在**提升单 Agent 的代码生成质量、工具调用成功率与长上下文推理能力**。

> * 厂商解决的是“Agent 能不能把这 500 行代码写对”；  
> * 至于 5 个 Agent 同时改代码会不会导致架构漂移、谁改了公共接口、多个任务如何避免分支爆炸，属于**系统级治理与护栏工程（Harness Engineering）**。这正是当前 AI 研发体系中，架构师与高级开发者最核心的工程壁垒所在。

**4\. Token 经济学与注意力控制** 如果平台在 UI 层默认开启全量状态与 SPEC 自动广播：

> * 每次任务变动都会产生不可预测的后台 Token 消耗；  
> * 过多的全局上下文注入会导致小模型产生注意力稀释或幻觉。将“何时同步、同步多少数据”的决定权交给代码库（通过 .specs/ 和 .sync/ 显式检索），是目前兼顾成本与精度的最优解。

这正是为什么需要自建脚本（如 workspace.sh 与 universal-task-sync）的原因：**厂商提供算力与执行沙箱，我们通过 Harness 为其注入架构纪律与协作灵魂。**

---

*User prompt: 如果我们自己通过skill来解决这些问题（multi task, worktree, peer-relay-dev），是否导致skill的功能太重，结构太复杂，代码太多？请推荐一种最好的方式，比如plugin 合适么?*

Response: 如果把 Git Worktree、SPEC 元数据状态机、文件监听 Watcher、WebSocket Broker 和跨 Agent 状态同步全塞进一个 Skill 里，**确实会导致 Skill 严重臃肿、上下文消耗过大，且极易因 Agent 幻觉引发执行不稳定**。

在 Harness Engineering 中，解决复杂度的黄金法则是：**“控制面与认知面分离（Separation of Control & Cognitive Planes）”**。

### **推荐的最佳架构方案：厚内核（CLI/Daemon）+ 薄插件（MCP Plugin / Thin Skill）**

不要把可执行代码和复杂逻辑写在 Skill 的 Prompt 里，而是采用三层解耦结构：

`┌─────────────────────────────────────────────────────────────┐`  
`│ 1. 认知层 (Thin Skill / Rules)  ~50 行 Prompt                │`  
`│    - 仅声明 SOP 行为准则，指导 Agent 何时调用工具            │`  
`└──────────────────────────────┬──────────────────────────────┘`  
                               `│ MCP 协议 / Tool Calls`  
`┌──────────────────────────────▼──────────────────────────────┐`  
`│ 2. 适配层 (MCP Plugin / Tool API)                           │`  
`│    - 向 Agent 暴露标准工具 (如 workspace_attach, post_uas)   │`  
`└──────────────────────────────┬──────────────────────────────┘`  
                               `│ 本地调用`  
`┌──────────────────────────────▼──────────────────────────────┐`  
`│ 3. 执行层 (Core Engine / CLI & Daemon)                      │`  
`│    - 独立运行的 workspace-cli、fswatch 与 merge-states 脚本 │`  
`│    - 负责 Git Worktree 物理创建、Diff 校验、JSON 文件总线聚合│`  
`└─────────────────────────────────────────────────────────────┘`

### **方案形态对比：为什么 Plugin / MCP 最合适？**

| 维度 | 单体庞大 Skill (Monolithic Prompt) | CLI \+ MCP 插件模式 (推荐) |
| :---- | :---- | :---- |
| **Token 消耗** | ❌ 极大（每次对话都要加载数百行脚本代码与规则） | ✅ 极小（仅注入工具签名和极简 SOP，节约 90% 上下文） |
| **执行确定性** | ❌ 差（Agent 可能记错 Bash 命令参数或跳过检查） | ✅ 强（由 MCP 工具代码在后台严格执行，结果确定） |
| **跨工具支持** | ⚠️ 各工具配置格式不同，维护繁琐 | ✅ **MCP 已成为事实标准**（Claude Code、Cursor、Windsurf、Antigravity 均原生支持） |
| **维护成本** | ❌ 逻辑修改需更新各处 Prompt | ✅ 逻辑封装在本地脚本中，修改底层逻辑无需调整 Agent Prompt |

### **具体落地三步走**

#### **1\. 底层：打包为独立的本地脚手架（Engine）**

将 workspace.sh、merge-states.py 和 watcher.sh 归拢为一个轻量 CLI 工具（如 agent-harness）：

> * 负责物理 Worktree 增删、SPEC 解析、impact\_scope 校验与 .sync/ 状态聚合。  
> * 本地后台常驻一个极轻量 Watcher 维护 MERGED\_STATE.md。

#### **2\. 中间层：封装为一个标准 MCP Plugin (mcp-server-harness)**

编写一个只有两百行代码的 MCP Server（Node.js 或 Python），向各类 AI IDE 暴露 4 个原子工具：

> * spec\_create(id, epic, title)：生成 SPEC 模板并同步注册表。  
> * workspace\_attach(epic, spec\_id)：挂载 Worktree 并切换环境。  
> * scope\_verify(spec\_id)：触发门禁检查当前 Diff 是否越权。  
> * state\_publish(uas\_json)：发布当前 Agent 的 UAS 动态心跳（支持 Concurrent 广播与 Relay 交接）。

#### **3\. 顶层：极简 Thin Skill / System Instruction**

在任何 AI 工具（Claude Code、Cursor、ZCode 等）中，只需保留不到 50 行的 SOP 引导：

`# Agent Collaboration Protocol`  
``1. [Planning] Call `spec_create` before starting new architectural work.``  
``2. [Coding] Call `workspace_attach` to enter the isolated epic worktree.``  
``3. [Heartbeat] Call `state_publish` when reaching milestones or before handoff.``  
``4. [Review] Call `scope_verify` before merging or finishing tasks.``

> * **结论**：**“CLI 承载逻辑 \+ MCP 插件暴露接口 \+ Thin Skill 约束行为”** 是目前最优雅、扩展性最强的架构。它既避免了单体 Skill 的臃肿失控，又保证了跨 Agent、跨工具协作的高效与安全。

---

