# 角色边界

| 角色 | 职责 | 不得 |
|---|---|---|
| A 设计 | 写 SPEC,声明范围、依赖、风险、必需证据 | 改业务代码 |
| B 验证 | 客观核对 SPEC 与实现,执行机检规则,登记证据 | 验证自己写的内容;替设计取舍背书 |
| C 开发 | 认领任务,在 Epic 沙箱内实现 | 自建分支或 worktree;把自己的工作标为通过 |
| D 审核 | 独立判断设计与实现的质量和风险,终审,清理沙箱 | 兼任同一 SPEC 的 B 或 C;HIGH/CRITICAL 下与 A、C 同底座 |
| H 人类 | 设计签发、发布签发 | 由模型代签 |

B 回答"做对了吗"(可核对、可复现);D 回答"该不该这样做"(判断与风险)。

## 模型底座族
glm、gemini、claude、gpt、deepseek 各算一族。别名(chatgpt、openai、zhipu、google、anthropic)自动归一,其他写法被拒绝。同族不同版本算同一底座。
HIGH/CRITICAL 的 D 审核必须与 A、C 异构;其余只记录 `same_backbone`。

## 局限
脚本无法鉴别身份:`--as`、`SPEC_ROLE`、签发的 by/ref 都是文本约定。真正的授权靠受保护分支、CODEOWNERS 和 PR 审查。
