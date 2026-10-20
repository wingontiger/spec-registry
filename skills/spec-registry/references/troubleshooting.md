# 常见报错

| 报错 | 原因 | 处理 |
|---|---|---|
| 请用 --as A\|B\|C\|D\|H 或环境变量 SPEC_ROLE | 没指定角色 | 设置 SPEC_ROLE,或加 --as |
| --model 必须是 [...] 之一 | 模型底座写法不在名单内 | 用 glm / gemini / claude / gpt / deepseek |
| 范围冲突 | 与活跃 SPEC 的 impact_scope 重叠 | 等对方完成,或调整范围;确需继续由用户同意后 --force |
| 缺少针对当前 SPEC 版本的人类设计签发 | 未签发,或签发后 SPEC 又被改过 | 由人类运行 `--as H signoff --kind design` |
| SPEC 在提交验证后被修改 | 哈希不一致 | 退回 draft,重新提交验证 |
| X 未提交到主工作区 | SPEC 还没 commit | 在主分支提交 .specs/ 后再 attach |
| 缺少针对当前提交的验证证据 | 没登记,或之后又有新提交 | 重新 `evidence` 登记 |
| 存在越界改动 | 改了 impact_scope 之外的文件 | 回退这些改动,或让 A 补充声明并重新走验证 |
| 提交被拦截(pre-commit) | 暂存区含越界文件 | 同上;孤儿沙箱则先 attach |
| 沙箱正被另一个 SPEC 占用 | 同一 Epic 沙箱一次只承载一个活跃 SPEC | 等前一个完成,或用不同 Epic |
| 分支尚未合入 | finish 前没合并 | 先合并分支,再 finish |
| hook 已存在且不是本工具生成的 | 项目已有 pre-commit | 手动合并,或 `install-hooks --force` |
