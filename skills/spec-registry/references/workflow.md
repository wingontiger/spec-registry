# 状态机与门禁

```
discovered ─A→ draft ─A→ verifying_spec ─B→ reviewing_spec ─D→ approved ─C(attach)→ in_progress
                ↑            │ B 退回        │ D 退回    (track=lite: B 直接 approved)       │ ↑
                └────────────┴───────────────┘   ★ approved 须有人类设计签发(lite 除外)  C │ │ B/D 退回
                                                                                      ▼ │
   done ←─D(finish)─ reviewing_impl ←──B── verifying_impl ←──────────────────────────────┘
任意状态 ─A 或 D→ superseded;  in_progress ⇄ blocked(C)
```

| 迁移 | 执行 | 脚本检查 |
|---|---|---|
| discovered → draft | A | 采纳的遗留 SPEC 经 A 确认后进入起草 |
| draft → verifying_spec | A | impact_scope 的 files 或 modules 非空;risk 合法;lite 只允许 LOW/MEDIUM;记录 SPEC 哈希 |
| verifying_spec → reviewing_spec | B | track=full;哈希未变 |
| verifying_spec → approved | B | track=lite;哈希未变;免人类签发 |
| reviewing_spec → approved | D | 哈希未变;须有针对当前哈希的人类设计签发;HIGH/CRITICAL 下 D 异构 |
| approved → in_progress | C,仅 attach | 哈希与签发有效;依赖就绪;范围无冲突;SPEC 已提交;沙箱未被占用 |
| in_progress → verifying_impl | C | 自认领以来的全部改动都在 impact_scope 内 |
| verifying_impl → reviewing_impl | B | 再次校验范围;required_evidence 每类都有针对当前提交的通过记录 |
| reviewing_impl → done | D,仅 finish | 分支已合入;沙箱干净;证据对当前提交有效;HIGH/CRITICAL 须有发布签发且 D 异构 |

## 失效规则
- SPEC 或 `.meta.yml` 一改:设计签发和批准作废。
- 分支一有新提交:证据和发布签发作废。
- 租约 4 小时,`heartbeat` 续租;过期后别的 C 可用 `attach --takeover` 接管(先读前任的交接记录)。

## 依赖写法
- `SPEC-009`:该 SPEC 已批准即可。
- `SPEC-123/U1`:只依赖该单元,由 B 用 `unit` 命令标记 verified 后放行。

## 证据类别
unit、mock、handler、provider、browser、cold_recovery、fault_injection、e2e、qa_report、human_uat。
