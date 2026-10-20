#!/usr/bin/env bash
# 冒烟测试: 在临时仓库里走完 A->B->(D)->人类签发->C->B->D 全流程, 并验证各道门禁会拦截;
# 最后把导出的 canonical 索引交给 ci/spec_registry.py 校验。
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W() { bash "$HERE/workspace.sh" "$@"; }
T="$(mktemp -d)"; cd "$T"
git init -q -b main . && git config user.email t@t && git config user.name t
mkdir -p services/order pkg handoff tests && echo a > services/order/handler.go && echo b > pkg/x.go
echo "# legacy spec 143" > handoff/spec_143_statemachine.md
git add -A && git commit -qm init
pass=0; fail=0
ok()   { if out=$("$@" 2>&1); then pass=$((pass+1)); echo "PASS  ${*:2}"; else fail=$((fail+1)); echo "FAIL  ${*:2}"; echo "      $out" | head -3; fi; }
deny() { if out=$("$@" 2>&1); then fail=$((fail+1)); echo "FAIL (应被拒绝)  ${*:2}"; else pass=$((pass+1)); echo "PASS (已拒绝)  ${*:2}"; echo "      -> $(echo "$out" | head -1)"; fi; }
approve_lite() { # $1=SPEC id; track=lite 免人类设计签发
  ok W --as A --model claude transition "$1" verifying_spec
  ok W --as B --model gpt transition "$1" approved
}

# ---------- 建 SPEC ----------
ok W --as A --model claude new-spec --id SPEC-001 --epic order --title t1
ok W --as A --model claude new-spec --id SPEC-002 --epic pay --title t2
ok W --as A --model claude new-spec --id SPEC-003 --epic ship --title t3
ok W --as A --model claude new-spec --id SPEC-004 --epic base --title t4
sed -i 's|^risk: MEDIUM|risk: HIGH|; s|^required_evidence: \[\]|required_evidence: [unit]|; s|files: \[\]|files: ["services/order/handler.go", "tests/t.py", "handoff/qa_001.md"]|' .specs/SPEC-001.md
sed -i 's|^track: full.*|track: lite|; 0,/files: \[\]/s||files: ["services/order/*.go"]|' .specs/SPEC-002.md
sed -i 's|^track: full.*|track: lite|; s|^depends_on: \[\]|depends_on: ["SPEC-004/U1"]|; 0,/files: \[\]/s||files: ["pkg/ship.go"]|' .specs/SPEC-003.md
sed -i 's|^track: full.*|track: lite|; 0,/files: \[\]/s||files: ["pkg/base.go"]|' .specs/SPEC-004.md
git add -A && git commit -qm specs

# ---------- 模型底座族 ----------
deny W --as A --model llama transition SPEC-001 verifying_spec          # 不在五族名单内
ok   W --as A --model ChatGPT new-spec --id SPEC-005 --epic misc --title t5   # 别名归一为 gpt
sed -i 's|^risk: MEDIUM|risk: HIGH|; s|^track: full.*|track: lite|; 0,/files: \[\]/s||files: ["pkg/lite.go"]|' .specs/SPEC-005.md
git add -A && git commit -qm spec5
deny W --as A --model deepseek transition SPEC-005 verifying_spec       # lite 不能用于 HIGH 风险

# ---------- SPEC-001: HIGH, full 轨道 ----------
deny W --as C transition SPEC-001 verifying_spec                       # 角色不对
ok   W --as A --model claude transition SPEC-001 verifying_spec
deny W --as B --model gpt transition SPEC-001 approved                 # track=full 不能跳过 D
ok   W --as B --model gpt transition SPEC-001 reviewing_spec
deny W --as D --model gemini transition SPEC-001 approved              # 缺少人类设计签发
ok   W --as H signoff --spec SPEC-001 --kind design --by wan --ref PR#1
deny W --as D --model claude transition SPEC-001 approved              # D 与 A 同底座
deny W --as D transition SPEC-001 approved                             # HIGH 必须声明模型
ok   W --as D --model gemini transition SPEC-001 approved
deny W --as C transition SPEC-001 in_progress                          # 必须走 attach
ok   W --as C --agent glm-1 --model glm attach --epic order --spec SPEC-001
mkdir -p .worktrees/epic-order/tests
echo changed > .worktrees/epic-order/services/order/handler.go
echo "pass" > .worktrees/epic-order/tests/t.py
ok   W check-scope --spec SPEC-001
echo bad > .worktrees/epic-order/pkg/x.go
git -C .worktrees/epic-order add -A && git -C .worktrees/epic-order commit -qm "越界提交"
deny W check-scope --spec SPEC-001                                     # 提交之后仍能发现越界
git -C .worktrees/epic-order reset -q --hard HEAD~1
mkdir -p .worktrees/epic-order/tests
echo changed > .worktrees/epic-order/services/order/handler.go
echo "pass" > .worktrees/epic-order/tests/t.py
echo "独立 QA 报告" > .worktrees/epic-order/handoff/qa_001.md
git -C .worktrees/epic-order add -A && git -C .worktrees/epic-order commit -qm impl
ok   W check-scope --spec SPEC-001
ok   W --as C --model glm transition SPEC-001 verifying_impl
deny W --as B --model gpt transition SPEC-001 reviewing_impl           # 缺少 unit 证据
ok   W --as B --model gpt evidence --spec SPEC-001 --class unit --path tests/t.py --result pass
echo "more" >> .worktrees/epic-order/tests/t.py
git -C .worktrees/epic-order commit -qam "再改一次"
deny W --as B --model gpt transition SPEC-001 reviewing_impl           # 证据针对旧提交, 已过期
ok   W --as B --model gpt evidence --spec SPEC-001 --class unit --path tests/t.py --result pass
deny W --as C --model glm transition SPEC-001 reviewing_impl           # 开发者不能自己推进
ok   W --as B --model gpt transition SPEC-001 reviewing_impl
ok   W --as D --model gemini evidence --spec SPEC-001 --class qa_report --path handoff/qa_001.md --result pass

# ---------- 范围/依赖/单元 ----------
approve_lite SPEC-002
deny W --as C --agent g2 --model glm attach --epic pay --spec SPEC-002 # 与 SPEC-001 范围重叠
approve_lite SPEC-004
approve_lite SPEC-003
deny W --as C --agent g3 --model glm attach --epic ship --spec SPEC-003 # 依赖 SPEC-004/U1 未验证
ok   W --as B --model gpt unit --spec SPEC-004 --unit U1
ok   W --as C --agent g3 --model glm attach --epic ship --spec SPEC-003

# ---------- 合并与发布 ----------
deny W --as D --model gemini finish --epic order                       # 分支未合并
git merge -q --no-ff epic/order -m merge
deny W --as D --model gemini finish --epic order                       # 缺人类发布签发
ok   W --as H signoff --spec SPEC-001 --kind release --by wan --ref PR#2
deny W --as D --model claude finish --epic order                       # D 与 A 同底座
ok   W --as D --model gemini finish --epic order
ok   W status

# ---------- 遗留 SPEC 采纳 ----------
ok   W --as A adopt --id SPEC-143 --path handoff/spec_143_statemachine.md --epic sm --risk CRITICAL
deny W --as A adopt --id SPEC-144 --path ../outside.md --epic sm       # 路径穿越
ok   W --as A --model claude transition SPEC-143 draft
deny W --as A --model claude transition SPEC-143 verifying_spec        # impact_scope 为空
sed -i 's|files: \[\]|files: ["services/sm/*.go"]|' .specs/SPEC-143.meta.yml
ok   W --as A --model claude transition SPEC-143 verifying_spec
echo "# 偷偷改了范围之外的元数据" >> .specs/SPEC-143.meta.yml
deny W --as B --model gpt transition SPEC-143 reviewing_spec           # sidecar 在提交验证后被改

# ---------- L0/L1 摘要与 pre-commit 硬门禁 ----------
ok   W overview
ok   W related --spec SPEC-003
ok   W install-hooks
mkdir -p scripts/spec-registry && cp "$HERE/workspace.py" scripts/spec-registry/workspace.py
git add -A && git commit -qm "vendor tool" -q
# SPEC-003 的沙箱(epic-ship)里提交越界文件应被 hook 拦截
echo x > .worktrees/epic-ship/pkg/ship.go; echo y > .worktrees/epic-ship/pkg/other.go
git -C .worktrees/epic-ship add -A
deny git -C .worktrees/epic-ship commit -qm "越界"
git -C .worktrees/epic-ship reset -q pkg/other.go; rm -f .worktrees/epic-ship/pkg/other.go
ok   git -C .worktrees/epic-ship commit -qm "范围内提交"

# ---------- 导出 canonical 索引, 交给 ci/spec_registry.py 校验 ----------
ok   W export-registry --out "$T/registry/spec_registry.json"
cp "$HERE/ci/spec_registry.py" "$T/spec_registry_ci.py"
git add -A && git commit -qm "registry export" -q
ok   python3 spec_registry_ci.py summary --registry registry/spec_registry.json
ok   python3 spec_registry_ci.py validate --root . --registry registry/spec_registry.json
ok   python3 spec_registry_ci.py gate --root . --registry registry/spec_registry.json --spec SPEC-001 --phase release
deny python3 spec_registry_ci.py gate --root . --registry registry/spec_registry.json --spec SPEC-143 --phase dev   # 未批准

echo "---- $pass passed, $fail failed"; [ "$fail" -eq 0 ]
