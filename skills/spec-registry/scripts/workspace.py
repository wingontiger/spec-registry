#!/usr/bin/env python3
"""SPEC Registry v0.3 - workspace CLI (运行时协调层).

角色: A 设计 / B 验证 / C 开发 / D 审核 / H 人类(仅签发)。角色通过 --as 或环境变量 SPEC_ROLE 指定。
与入库的 canonical 索引(registry/spec_registry.json, 由 export-registry 生成,
用 ci/spec_registry.py 在 CI 中校验)配合使用。
布局:
  <主工作区>/.specs/SPEC-*.md          SPEC 正文 (入库, 唯一事实来源, 须先提交到主分支)
  <主工作区>/.worktrees/epic-<name>/   Epic 沙箱 (不入库)
  <git common dir>/spec-registry/      实时状态 state/*.json、registry.json、ACTIVE_TASKS.md (不入库)
"""
import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

LEASE_HOURS = 4
MAX_WORKTREES = 5
ACTIVE = {"in_progress", "verifying_impl", "reviewing_impl"}
DONE_LIKE = {"done", "superseded"}
ORDER = ["discovered", "draft", "verifying_spec", "reviewing_spec", "approved",
         "in_progress", "verifying_impl", "reviewing_impl", "done"]

# (from, to) -> 允许的角色
READONLY = {"precommit", "overview", "related", "check-scope", "conflicts"}
RISKS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
# 模型底座族: 每个族算一个独立底座。不在名单内的写法会被拒绝, 避免拼写差异绕过独立性检查。
FAMILIES = {"glm", "gemini", "claude", "gpt", "deepseek"}
FAMILY_ALIASES = {"chatgpt": "gpt", "openai": "gpt", "zhipu": "glm", "chatglm": "glm",
                  "google": "gemini", "anthropic": "claude"}
CLASSES = {"unit", "mock", "handler", "provider", "browser", "cold_recovery",
           "fault_injection", "e2e", "qa_report", "human_uat"}
QA_CLASSES = {"qa_report", "human_uat"}
EXPORT_STATUS = {"discovered": "DISCOVERED", "draft": "DRAFT", "verifying_spec": "IN_REVIEW",
                 "reviewing_spec": "IN_REVIEW", "approved": "APPROVED", "in_progress": "IMPLEMENTING",
                 "blocked": "IMPLEMENTING", "verifying_impl": "IMPLEMENTING",
                 "reviewing_impl": "IMPLEMENTING", "done": "VERIFIED", "superseded": "SUPERSEDED"}
T = {
    ("discovered", "draft"): "A",
    ("draft", "verifying_spec"): "A",
    ("verifying_spec", "draft"): "B",
    ("verifying_spec", "reviewing_spec"): "B",   # track=full
    ("verifying_spec", "approved"): "B",         # track=lite
    ("reviewing_spec", "draft"): "D",
    ("reviewing_spec", "approved"): "D",
    ("in_progress", "verifying_impl"): "C",
    ("in_progress", "blocked"): "C",
    ("blocked", "in_progress"): "C",
    ("verifying_impl", "in_progress"): "B",
    ("verifying_impl", "reviewing_impl"): "B",
    ("reviewing_impl", "in_progress"): "D",
}
# 只能通过专用命令完成的迁移
VIA = {("approved", "in_progress"): "attach", ("reviewing_impl", "done"): "finish"}

TEMPLATE = """---
id: {id}
epic: "{epic}"
title: "{title}"
task_id: "{task}"
track: full            # full = 须经 D 设计审核; lite = 小改动, 跳过 D 设计审核(人类签发仍必需)
risk: MEDIUM           # LOW | MEDIUM | HIGH | CRITICAL; HIGH 及以上要求异构审核和人类发布签发
owner: "{owner}"
created_at: "{today}"
tags: []
depends_on: []          # "SPEC-001"(已批准即可) 或 "SPEC-001/U1"(该单元已验证)
blocks: []
required_evidence: []   # 如 [unit, fault_injection]; 进入 reviewing_impl 前须有当前提交的通过记录
impact_scope:
  modules: []          # 目录前缀, 授权整个目录
  files: []            # 精确路径或 glob
  api_endpoints: []
  db_entities: []
rules: []              # 适用的 DL-xx 规则 ID
---

## 1. 背景与动机

## 2. 核心变更设计

## 3. 依赖与破坏性变更

## 4. 验收标准
- [ ] 测试通过
- [ ] 仅改动 impact_scope 内的文件
"""


def die(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def info(msg):
    print(f"[INFO] {msg}")


def now():
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def sh(*args, cwd=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        die(f"{' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def rc(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True).returncode


COMMON = (Path.cwd() / sh("git", "rev-parse", "--git-common-dir").strip()).resolve()
if COMMON.name != ".git":
    die("不支持 bare 仓库")
MAIN = COMMON.parent
SPECS, WT, REG = MAIN / ".specs", MAIN / ".worktrees", COMMON / "spec-registry"
STATE = REG / "state"


# ---------------------------------------------------------------- 存储
def spec_rel(sid):
    p = STATE / f"{sid}.json"
    if p.exists():
        return json.loads(p.read_text("utf-8")).get("path") or f".specs/{sid}.md"
    return f".specs/{sid}.md"


def spec_path(sid):
    return MAIN / spec_rel(sid)


def sidecar(sid):
    return SPECS / f"{sid}.meta.yml"


def meta(sid):
    """frontmatter 优先; 遗留 SPEC(无 frontmatter)用 .specs/<id>.meta.yml。"""
    p = spec_path(sid)
    if not p.exists():
        die(f"未找到 {p}")
    m = re.match(r"\A\ufeff?---\r?\n(.*?)\r?\n---\r?\n", p.read_text("utf-8"), re.S)
    try:
        if m:
            return yaml.safe_load(m.group(1)) or {}
        if sidecar(sid).exists():
            return yaml.safe_load(sidecar(sid).read_text("utf-8")) or {}
    except yaml.YAMLError as e:
        die(f"{sid} 的元数据不是合法 YAML: {str(e).splitlines()[0]}")
    die(f"{p.name} 缺少 YAML frontmatter, 也没有 {sidecar(sid).name}")


def fhash(sid):
    """SPEC 文件原始字节的 SHA-256(与 ci/spec_registry.py 一致)。Windows 下请用 .gitattributes 固定 LF。"""
    return hashlib.sha256(spec_path(sid).read_bytes()).hexdigest()


def mhash(sid):
    """遗留 SPEC 的 sidecar 元数据哈希; 使用 frontmatter 时为 None。"""
    return hashlib.sha256(sidecar(sid).read_bytes()).hexdigest() if \
        sidecar(sid).exists() and not spec_path(sid).read_text("utf-8").lstrip("\ufeff").startswith("---") else None


def load(sid):
    p = STATE / f"{sid}.json"
    if not p.exists():
        die(f"{sid} 未登记, 先运行 new-spec 或 adopt")
    return json.loads(p.read_text("utf-8"))


def save(s):
    s["rev"] = s.get("rev", 0) + 1
    s["updated_at"] = iso(now())
    p = STATE / f"{s['id']}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, p)


def all_states():
    return [json.loads(p.read_text("utf-8")) for p in sorted(STATE.glob("SPEC-*.json"))]


def new_state(sid, epic, path, a, note):
    s = {"id": sid, "epic": epic, "status": "draft", "rev": 0, "path": path,
         "spec_hash": None, "meta_hash": None, "claim": None, "units": {},
         "signoffs": {}, "evidence": [], "history": []}
    return s


def move(s, to, role, a, note="", **extra):
    s["history"].append({"at": iso(now()), "from": s["status"], "to": to, "role": role,
                         "agent": a.agent, "model": a.model, "note": note, **extra})
    s["status"] = to


def role_of(a):
    r = (a.role or os.environ.get("SPEC_ROLE", "")).upper()
    if r not in list("ABCDH"):
        die("请用 --as A|B|C|D|H 或环境变量 SPEC_ROLE 指定角色")
    return r


def safe_rel(p):
    if not isinstance(p, str) or not p or "\\" in p or ":" in p or p.startswith("/") or ".." in Path(p).parts:
        die(f"不安全的相对路径: {p!r}")
    return p


# ---------------------------------------------------------------- 风险、独立性、证据
def risk_of(m):
    r = str(m.get("risk", "MEDIUM")).upper()
    if r not in RISKS:
        die(f"risk 必须是 {RISKS}")
    return r


def high(m):
    return risk_of(m) in ("HIGH", "CRITICAL")


def indep(s, role, a, m):
    """B/D 的模型底座是否与 A/C 相同。D 在 HIGH/CRITICAL 下同底座直接拒绝; 其余只记录。"""
    model = a.model
    known = bool(model) and model != "unknown"
    others = {h["model"] for h in s["history"] if h["role"] in ("A", "C")
              and h.get("model") not in (None, "", "unknown")}
    same = known and model in others
    if role == "D" and high(m):
        if not known:
            die("HIGH/CRITICAL 的 D 审核必须用 --model 声明模型底座")
        if same:
            die(f"D 与 A/C 同底座({model}), HIGH/CRITICAL 须异构审查")
    return bool(same)


def head_of(s):
    return sh("git", "-C", s["claim"]["worktree"], "rev-parse", "HEAD").strip()


def missing_evidence(s, head):
    """required_evidence 中, 没有针对当前提交和已验证 SPEC 哈希的最新通过记录的类别。"""
    out = []
    for cls in meta(s["id"]).get("required_evidence") or []:
        recs = [e for e in s["evidence"] if e["class"] == cls]
        last = recs[-1] if recs else None
        if not (last and last["result"] == "pass" and last["commit"] == head
                and last["spec_hash"] == s["spec_hash"]):
            out.append(cls + ("(无记录)" if not last else "(失败或已过期)"))
    return out


def check_hashes(s):
    if s["spec_hash"] != fhash(s["id"]) or s.get("meta_hash") != mhash(s["id"]):
        die("SPEC(或其 .meta.yml)在提交验证后被修改, 须退回 draft 重新提交")


# ---------------------------------------------------------------- 范围与冲突
def allowed(path, sc):
    for p in sc.get("files") or []:
        if path == p or fnmatch.fnmatch(path, p) or (p.endswith("/") and path.startswith(p)):
            return True
    for m in sc.get("modules") or []:
        if path.startswith(m.rstrip("/") + "/"):
            return True
    return False


def out_of_scope(s):
    """分支自认领以来的全部改动(提交 + 暂存 + 未暂存 + 未跟踪)中, 超出 impact_scope 的文件。"""
    c = s.get("claim")
    if not c:
        die(f"{s['id']} 尚未认领")
    sc = meta(s["id"]).get("impact_scope") or {}
    wt, base = c["worktree"], c["base"]
    names = set()
    for cmd in (["diff", "--name-only", "-z", f"{base}...HEAD"],
                ["diff", "--name-only", "-z", "HEAD"],
                ["ls-files", "--others", "--exclude-standard", "-z"]):
        names |= {x for x in sh("git", "-C", wt, *cmd).split("\0") if x}
    return [p for p in sorted(names) if not p.startswith(".specs/") and not allowed(p, sc)]


def _prefixes(sc):
    """-> [(prefix, exact)]; 目录/glob 取前缀, 精确文件 exact=True。"""
    out = []
    for m in sc.get("modules") or []:
        out.append((m.rstrip("/") + "/", False))
    for f in sc.get("files") or []:
        if re.search(r"[*?\[]", f):
            out.append((re.split(r"[*?\[]", f)[0], False))
        elif f.endswith("/"):
            out.append((f, False))
        else:
            out.append((f, True))
    return out


def overlaps(m1, m2):
    s1, s2 = m1.get("impact_scope") or {}, m2.get("impact_scope") or {}
    hits = []
    for (p, e1) in _prefixes(s1):
        for (q, e2) in _prefixes(s2):
            if (p == q) if (e1 and e2) else (p.startswith(q) or q.startswith(p)):
                hits.append(f"路径 {p} ~ {q}")
    for key in ("api_endpoints", "db_entities"):
        a = {x.strip().lower() for x in s1.get(key) or []}
        b = {x.strip().lower() for x in s2.get(key) or []}
        hits += [f"{key}: {x}" for x in sorted(a & b)]
    return hits


def conflicts_of(sid):
    me = meta(sid)
    res = []
    for o in all_states():
        if o["id"] != sid and o["status"] in ACTIVE:
            h = overlaps(me, meta(o["id"]))
            if h:
                res.append((o["id"], h))
    return res


def lease_expired(s):
    c = s.get("claim")
    return bool(c) and c["lease_expires"] < iso(now())


def dep_ok(d):
    sid, _, unit = d.partition("/")
    ds = load(sid)
    if unit:
        return ds.get("units", {}).get(unit) == "verified"
    return ds["status"] in ORDER and ORDER.index(ds["status"]) >= ORDER.index("approved")


def need_design_signoff(s, m):
    """track=lite(小改动)免人类设计签发; 其余必须有针对当前 SPEC 哈希的签发。"""
    if m.get("track", "full") == "lite":
        return
    g = s["signoffs"].get("design")
    if not g or g["spec_hash"] != s["spec_hash"]:
        die("缺少针对当前 SPEC 版本的人类设计签发, 请由人类运行: --as H signoff --kind design --by <名> --ref <PR/Issue>")


# ---------------------------------------------------------------- 命令
def cmd_new_spec(a):
    if role_of(a) != "A":
        die("new-spec 仅限角色 A")
    if not re.fullmatch(r"SPEC-\d+", a.id):
        die("--id 格式应为 SPEC-<数字>")
    if spec_path(a.id).exists() or (STATE / f"{a.id}.json").exists():
        die(f"{a.id} 已存在")
    SPECS.mkdir(exist_ok=True)
    spec_path(a.id).write_text(TEMPLATE.format(
        id=a.id, epic=a.epic, title=a.title, task=a.task or f"TASK-{a.id}",
        owner=a.owner, today=now().strftime("%Y-%m-%d")), "utf-8")
    s = new_state(a.id, a.epic, f".specs/{a.id}.md", a, "")
    s["history"].append({"at": iso(now()), "from": None, "to": "draft", "role": "A",
                         "agent": a.agent, "model": a.model, "note": "new-spec"})
    save(s)
    info(f"已创建 {spec_path(a.id)}; 填写后请先提交到主分支, 再 transition 到 verifying_spec")


def cmd_adopt(a):
    """把已有的遗留 SPEC 文件登记为 discovered(不假设它已被批准)。"""
    if role_of(a) != "A":
        die("adopt 仅限角色 A")
    if not re.fullmatch(r"SPEC-\d+", a.id):
        die("--id 格式应为 SPEC-<数字>")
    rel = safe_rel(a.path)
    if not (MAIN / rel).is_file():
        die(f"文件不存在: {rel}")
    if (STATE / f"{a.id}.json").exists():
        die(f"{a.id} 已登记")
    if a.risk.upper() not in RISKS:
        die(f"--risk 必须是 {RISKS}")
    has_fm = (MAIN / rel).read_text("utf-8").lstrip("\ufeff").startswith("---")
    if not has_fm and not sidecar(a.id).exists():
        SPECS.mkdir(exist_ok=True)
        sidecar(a.id).write_text(yaml.safe_dump({
            "id": a.id, "epic": a.epic, "title": a.title or a.id, "track": "full",
            "risk": a.risk.upper(), "depends_on": [], "required_evidence": [], "rules": [],
            "impact_scope": {"modules": [], "files": [], "api_endpoints": [], "db_entities": []},
        }, allow_unicode=True, sort_keys=False), "utf-8")
        info(f"已生成 {sidecar(a.id)}, 请补全 impact_scope 并提交")
    s = new_state(a.id, a.epic, rel, a, "")
    s["status"] = "discovered"
    s["history"].append({"at": iso(now()), "from": None, "to": "discovered", "role": "A",
                         "agent": a.agent, "model": a.model, "note": "adopt"})
    save(s)
    info(f"{a.id} 已登记为 discovered(文件存在不代表已批准或已实现)")


def cmd_transition(a):
    role, s = role_of(a), load(a.spec)
    frm, to = s["status"], a.to
    m = meta(a.spec)
    flag = {}
    if to == "superseded":
        if role not in ("A", "D"):
            die("superseded 仅限 A 或 D")
    else:
        if (frm, to) in VIA:
            die(f"{frm}->{to} 须通过 `{VIA[(frm, to)]}` 命令")
        need = T.get((frm, to))
        if not need:
            die(f"不允许的迁移 {frm}->{to}")
        if role != need:
            die(f"{frm}->{to} 只能由角色 {need} 执行 (当前 {role})")
        track = m.get("track", "full")
        if (frm, to) == ("verifying_spec", "approved") and track != "lite":
            die("track=full 须先转 reviewing_spec, 由 D 做设计审核")
        if (frm, to) == ("verifying_spec", "reviewing_spec") and track == "lite":
            die("track=lite 不需要 D 设计审核, 请直接 approved")
        if frm == "draft":
            sc = m.get("impact_scope") or {}
            if not (sc.get("files") or sc.get("modules")):
                die("impact_scope.files / modules 为空, 无法提交验证")
            if m.get("track", "full") == "lite" and high(m):
                die("track=lite 只允许 LOW/MEDIUM 风险; HIGH/CRITICAL 必须走 full 轨道")
            risk_of(m)
            s["spec_hash"], s["meta_hash"] = fhash(a.spec), mhash(a.spec)
            s["signoffs"].pop("design", None)
        if to in ("reviewing_spec", "approved"):
            check_hashes(s)
        if to == "approved":
            need_design_signoff(s, m)
        if role in ("B", "D"):
            flag = {"same_backbone": indep(s, role, a, m)}
        if (frm, to) in (("in_progress", "verifying_impl"), ("verifying_impl", "reviewing_impl")):
            bad = out_of_scope(s)
            if bad:
                die("存在越界改动:\n  " + "\n  ".join(bad))
        if (frm, to) == ("verifying_impl", "reviewing_impl"):
            miss = missing_evidence(s, head_of(s))
            if miss:
                die("缺少针对当前提交的验证证据: " + ", ".join(miss))
    move(s, to, role, a, a.note or "", **flag)
    save(s)
    info(f"{a.spec}: {frm} -> {to}" + (" (注意: 与 A/C 同底座)" if flag.get("same_backbone") else ""))


def cmd_signoff(a):
    """人类签发。注意这里只记录文本, 不构成身份鉴定; 真正的授权须靠受保护分支 / CODEOWNERS / PR 审查。"""
    if role_of(a) != "H":
        die("signoff 仅限人类(--as H)")
    s = load(a.spec)
    if a.kind == "design":
        if s["status"] not in ("verifying_spec", "reviewing_spec"):
            die("设计签发须在 verifying_spec 或 reviewing_spec 阶段进行")
        check_hashes(s)
        s["signoffs"]["design"] = {"by": a.by, "ref": a.ref, "spec_hash": s["spec_hash"], "at": iso(now())}
    else:
        if s["status"] != "reviewing_impl":
            die("发布签发须在 reviewing_impl 阶段进行")
        s["signoffs"]["release"] = {"by": a.by, "ref": a.ref, "commit": head_of(s), "at": iso(now())}
    save(s)
    info(f"{a.spec}: 已记录 {a.kind} 签发(by {a.by}, ref {a.ref})。NOTICE: 文本不是授权证明, 请同时走受保护 PR 审查")


def cmd_evidence(a):
    role = role_of(a)
    if role not in ("B", "C", "D"):
        die("evidence 仅限 B / C / D")
    if a.cls not in CLASSES:
        die(f"--class 必须是 {sorted(CLASSES)}")
    s = load(a.spec)
    if not s.get("claim"):
        die("尚未认领, 无法关联提交")
    rel = safe_rel(a.path)
    f = Path(s["claim"]["worktree"]) / rel
    if not f.is_file():
        die(f"证据文件不存在: {rel}")
    s["evidence"].append({
        "class": a.cls, "path": rel, "result": a.result, "commit": head_of(s),
        "spec_hash": s["spec_hash"], "file_sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
        "by": role, "agent": a.agent, "model": a.model, "at": iso(now()), "note": a.note or ""})
    save(s)
    info(f"{a.spec}: 已记录 {a.cls} 证据({a.result}), 绑定提交 {s['evidence'][-1]['commit'][:10]}。此证据不外推到其他类别")


def cmd_unit(a):
    if role_of(a) != "B":
        die("unit 仅限 B")
    s = load(a.spec)
    if ORDER.index(s["status"]) < ORDER.index("approved") if s["status"] in ORDER else True:
        die("单元只能在 SPEC 已批准后标记")
    s["units"][a.unit] = a.status
    s["history"].append({"at": iso(now()), "from": s["status"], "to": s["status"], "role": "B",
                         "agent": a.agent, "model": a.model, "note": f"unit {a.unit}={a.status}"})
    save(s)
    info(f"{a.spec}/{a.unit} = {a.status}")


def cmd_attach(a):
    if role_of(a) != "C":
        die("attach 仅限角色 C")
    s, m = load(a.spec), meta(a.spec)
    if m.get("epic") != a.epic:
        die(f"{a.spec} 属于 epic '{m.get('epic')}', 不是 '{a.epic}'")
    if s["status"] == "in_progress" and a.takeover:
        if not lease_expired(s):
            die("租约未过期, 不能接管")
    elif s["status"] != "approved":
        die(f"{a.spec} 状态为 {s['status']}, 只有 approved 才能认领")
    check_hashes(s)
    need_design_signoff(s, m)
    for rel in (spec_rel(a.spec), f".specs/{a.spec}.meta.yml"):
        if not (MAIN / rel).exists():
            continue
        if rc("git", "-C", str(MAIN), "ls-files", "--error-unmatch", rel) != 0 or \
                sh("git", "-C", str(MAIN), "status", "--porcelain", "--", rel).strip():
            die(f"{rel} 未提交到主工作区, 请先提交")
    for d in m.get("depends_on") or []:
        if not dep_ok(d):
            die(f"依赖 {d} 尚未就绪")
    for o in all_states():
        if o["id"] != a.spec and o["status"] in ACTIVE and o.get("claim") \
                and o["claim"]["epic"] == a.epic:
            die(f"Epic {a.epic} 的沙箱正被 {o['id']} 占用, 同一沙箱一次只承载一个活跃 SPEC")
    cf = conflicts_of(a.spec)
    if cf and not a.force:
        die("范围冲突:\n  " + "\n  ".join(f"{i}: {'; '.join(h)}" for i, h in cf)
            + "\n(确需继续请加 --force 并说明原因)")
    path, branch = WT / f"epic-{a.epic}", f"epic/{a.epic}"
    if str(path.resolve()) not in {str(Path(x.split(' ', 1)[1]).resolve()) for x in
                                   sh("git", "-C", str(MAIN), "worktree", "list", "--porcelain").splitlines()
                                   if x.startswith("worktree ")}:
        if len(list(WT.glob("epic-*"))) >= MAX_WORKTREES:
            die(f"活跃沙箱已达上限 {MAX_WORKTREES}, 请先 finish 一个 Epic")
        WT.mkdir(exist_ok=True)
        if rc("git", "-C", str(MAIN), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}") == 0:
            sh("git", "-C", str(MAIN), "worktree", "add", str(path), branch)
        else:
            sh("git", "-C", str(MAIN), "worktree", "add", "-b", branch, str(path), "HEAD")
        ex = COMMON / "info" / "exclude"
        ex.parent.mkdir(exist_ok=True)
        if ".worktrees/" not in (ex.read_text() if ex.exists() else ""):
            with ex.open("a") as f:
                f.write(".worktrees/\n")
    base = sh("git", "-C", str(path), "rev-parse", "HEAD").strip()
    s["claim"] = {"epic": a.epic, "worktree": str(path), "branch": branch, "base": base,
                  "agent": a.agent, "lease_expires": iso(now() + dt.timedelta(hours=LEASE_HOURS)),
                  "forced": bool(cf and a.force)}
    move(s, "in_progress", "C", a, "takeover" if a.takeover else "attach")
    save(s)
    info(f"已认领 {a.spec}。沙箱: {path}\n       SPEC 正文: {spec_path(a.spec)}")


def cmd_check_scope(a):
    bad = out_of_scope(load(a.spec))
    if bad:
        die("以下文件未在 impact_scope 声明:\n  " + "\n  ".join(bad))
    info(f"{a.spec} 范围校验通过")


def cmd_conflicts(a):
    ids = [a.spec] if a.spec else [s["id"] for s in all_states() if s["status"] in ACTIVE]
    found = False
    for sid in ids:
        for o, h in conflicts_of(sid):
            found = True
            print(f"{sid} <-> {o}: {'; '.join(h)}")
    if not found:
        info("无范围冲突")


def cmd_heartbeat(a):
    if role_of(a) != "C":
        die("heartbeat 仅限角色 C")
    s = load(a.spec)
    if not s.get("claim") or s["status"] not in ACTIVE | {"blocked"}:
        die(f"{a.spec} 当前没有有效认领")
    s["claim"]["lease_expires"] = iso(now() + dt.timedelta(hours=LEASE_HOURS))
    save(s)
    info(f"租约已续至 {s['claim']['lease_expires']}")


def cmd_finish(a):
    role = role_of(a)
    if role != "D":
        die("finish 仅限角色 D")
    sts = [s for s in all_states() if s["status"] == "reviewing_impl" and s["epic"] == a.epic]
    if not sts:
        die(f"Epic {a.epic} 没有处于 reviewing_impl 的 SPEC")
    branch, path = f"epic/{a.epic}", WT / f"epic-{a.epic}"
    if rc("git", "-C", str(MAIN), "merge-base", "--is-ancestor", branch, "HEAD") != 0:
        die(f"分支 {branch} 尚未合入主工作区当前分支, 请先合并")
    if path.exists() and sh("git", "-C", str(path), "status", "--porcelain").strip():
        die("沙箱有未提交改动, 拒绝清理")
    head = sh("git", "-C", str(MAIN), "rev-parse", branch).strip()
    for s in sts:
        m = meta(s["id"])
        miss = missing_evidence(s, head)
        if miss:
            die(f"{s['id']} 缺少针对当前提交的验证证据: " + ", ".join(miss))
        rel = s["signoffs"].get("release")
        if high(m) and not (rel and rel["commit"] == head):
            die(f"{s['id']} 风险 {risk_of(m)}: 缺少针对当前提交的人类发布签发 (--as H signoff --kind release)")
        flag = {"same_backbone": indep(s, "D", a, m)}
        move(s, "done", "D", a, "finish", **flag)
        s["claim"] = None
        save(s)
    left = [s for s in all_states() if s["epic"] == a.epic and s["status"] in ACTIVE | {"blocked"}]
    if not left and path.exists():
        sh("git", "-C", str(MAIN), "worktree", "remove", str(path))
        sh("git", "-C", str(MAIN), "worktree", "prune")
        info("沙箱已清理")
    info(f"已完成: {', '.join(s['id'] for s in sts)}")


def export_entry(s):
    m = meta(s["id"])
    sig = s["signoffs"].get("design") or {}
    ev = s.get("evidence", [])
    paths = lambda pred: sorted({e["path"] for e in ev if pred(e["class"]) and e["result"] == "pass"})
    status = EXPORT_STATUS[s["status"]]
    if s["status"] == "done" and s["signoffs"].get("release"):
        status = "FROZEN"
    rev = [h for h in s["history"] if h["role"] in ("B", "D") and "same_backbone" in h]
    waived = not sig and m.get("track", "full") == "lite" and s["spec_hash"] is not None \
        and s["status"] not in ("discovered", "draft")
    return {
        "spec_id": s["id"], "title": m.get("title", s["id"]), "path": spec_rel(s["id"]),
        "status": status,
        "approved_by": sig.get("by") or ("policy:track=lite" if waived else None),
        "approval_ref": sig.get("ref") or ("track=lite 小改动免人类签发(项目规则, 非人类签发)" if waived else None),
        "signoff_waived": waived,
        "spec_sha256": s["spec_hash"],
        "dependencies": sorted({d.partition("/")[0] for d in m.get("depends_on") or []}),
        "depends_on_units": [d for d in m.get("depends_on") or [] if "/" in d],
        "verify_paths": paths(lambda c: c not in QA_CLASSES),
        "qa_paths": paths(lambda c: c in QA_CLASSES),
        "risk": risk_of(m), "epic": s["epic"],
        "release_ref": (s["signoffs"].get("release") or {}).get("ref"),
        "same_backbone_reviews": sum(1 for h in rev if h["same_backbone"]),
    }


def cmd_export(a):
    data = {"schema_version": "1.0", "registry_state": "EXPORTED_FROM_RUNTIME_STATE",
            "as_of": now().strftime("%Y-%m-%d"),
            "note": "由 workspace.py export-registry 生成。入库须经受保护 PR 的人类审查; 文本字段不构成授权。",
            "specs": [export_entry(s) for s in all_states()]}
    out = json.dumps(data, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(out + "\n", "utf-8")
        info(f"已写入 {a.out}")
    else:
        print(out)


def cmd_status(_a):
    sts = all_states()
    REG.mkdir(exist_ok=True)
    (REG / "registry.json").write_text(json.dumps(
        {"schema_version": "0.3", "generated_at": iso(now()), "specs": sts},
        ensure_ascii=False, indent=2), "utf-8")
    rows = ["| SPEC | Epic | 状态 | 认领者 | 租约 |", "| --- | --- | --- | --- | --- |"]
    for s in sts:
        c = s.get("claim") or {}
        lease = (c.get("lease_expires", "-") + (" (已过期)" if lease_expired(s) else "")) if c else "-"
        rows.append(f"| {s['id']} | {s['epic']} | {s['status']} | {c.get('agent', '-')} | {lease} |")
    board = "\n".join(rows)
    (REG / "ACTIVE_TASKS.md").write_text(f"# SPEC 看板 ({iso(now())})\n\n{board}\n", "utf-8")
    (REG / "SPEC_OVERVIEW.md").write_text(overview_text(), "utf-8")
    print(board)
    print()
    print(sh("git", "-C", str(MAIN), "worktree", "list").rstrip())


def overview_text():
    """L0 常驻摘要: 每个 SPEC 一行, 适合直接放进 Agent 上下文。"""
    lines = ["# SPEC 总览 (L0)", f"> 生成于 {iso(now())}; 详情用 `related --spec <ID>` 按需加载", ""]
    for s in all_states():
        try:
            m = meta(s["id"])
        except SystemExit:
            continue
        sc = m.get("impact_scope") or {}
        where = ", ".join((sc.get("modules") or []) + (sc.get("files") or []))[:80] or "-"
        who = (s.get("claim") or {}).get("agent", "-")
        lines.append(f"- {s['id']} [{s['status']}] epic={s['epic']} risk={m.get('risk', 'MEDIUM')} "
                     f"by={who} :: {m.get('title', '')} | 范围: {where}")
    return "\n".join(lines) + "\n"


def cmd_overview(_a):
    txt = overview_text()
    REG.mkdir(exist_ok=True)
    (REG / "SPEC_OVERVIEW.md").write_text(txt, "utf-8")
    print(txt, end="")


def cmd_related(a):
    """L1 按需加载: 与指定 SPEC 范围重叠、被它依赖、或同 Epic 的 SPEC 详情。"""
    me = meta(a.spec)
    deps = {d.partition("/")[0] for d in me.get("depends_on") or []}
    me_epic = load(a.spec)["epic"]
    out = []
    for o in all_states():
        if o["id"] == a.spec:
            continue
        om = meta(o["id"])
        why = []
        if o["id"] in deps:
            why.append("被依赖")
        if o["epic"] == me_epic:
            why.append("同 Epic")
        hits = overlaps(me, om)
        if hits:
            why.append("范围重叠: " + "; ".join(hits))
        if why:
            out.append({"id": o["id"], "status": o["status"], "title": om.get("title"),
                        "why": why, "impact_scope": om.get("impact_scope")})
    print(json.dumps(out, ensure_ascii=False, indent=2) if out else "[]")


def cmd_precommit(_a):
    """git pre-commit 硬门禁: Epic 沙箱里的提交必须有已认领的活跃 SPEC, 且暂存文件都在 impact_scope 内。"""
    top = Path(sh("git", "rev-parse", "--show-toplevel").strip()).resolve()
    if top == MAIN.resolve():
        return  # 主工作区不拦截(设计提交走主分支)
    mine = [s for s in all_states() if s.get("claim") and s["status"] in ACTIVE | {"blocked"}
            and Path(s["claim"]["worktree"]).resolve() == top]
    if not mine:
        if top.parent == WT.resolve():
            die("该 Epic 沙箱没有已认领的活跃 SPEC(孤儿沙箱), 请先 attach")
        return
    sc = meta(mine[0]["id"]).get("impact_scope") or {}
    staged = [x for x in sh("git", "diff", "--cached", "--name-only", "-z").split("\0") if x]
    bad = [p for p in staged if not p.startswith(".specs/") and not allowed(p, sc)]
    if bad:
        die(f"提交被拦截: 以下文件未在 {mine[0]['id']} 的 impact_scope 声明:\n  " + "\n  ".join(bad))


HOOK_MARK = "# spec-registry managed hook"
HOOK = f"""#!/bin/sh
{HOOK_MARK}
ROOT="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"
PY="$(command -v python3 || command -v python)"
[ -f "$ROOT/scripts/spec-registry/workspace.py" ] || exit 0
exec "$PY" "$ROOT/scripts/spec-registry/workspace.py" precommit
"""


def cmd_install_hooks(a):
    hooks = COMMON / "hooks"
    hooks.mkdir(exist_ok=True)
    p = hooks / "pre-commit"
    if p.exists() and HOOK_MARK not in p.read_text("utf-8", errors="ignore"):
        if not a.force:
            die(f"{p} 已存在且不是本工具生成的; 请手动合并, 或加 --force 覆盖")
    if a.remove:
        if p.exists() and HOOK_MARK in p.read_text("utf-8", errors="ignore"):
            p.unlink()
            info("已移除 pre-commit hook")
        return
    p.write_text(HOOK, "utf-8")
    p.chmod(0o755)
    info(f"已安装 {p}(所有 worktree 共用)")


def acquire_lock():
    STATE.mkdir(parents=True, exist_ok=True)
    f = open(REG / ".lock", "a+")
    if os.name == "nt":  # Windows: 未经实机验证
        import msvcrt
        f.seek(0)
        if not f.read(1):
            f.write(" ")
            f.flush()
        f.seek(0)
        while True:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                time.sleep(0.2)
    else:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_EX)
    return f


def main():
    p = argparse.ArgumentParser(prog="workspace")
    p.add_argument("--as", dest="role", help="A|B|C|D|H, 默认读环境变量 SPEC_ROLE")
    p.add_argument("--agent", default=os.environ.get("SPEC_AGENT", "unknown"))
    p.add_argument("--model", default=os.environ.get("SPEC_MODEL", "unknown"),
                   help="模型底座族: glm / gemini / claude / gpt / deepseek, 用于独立性检查")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new-spec")
    n.add_argument("--id", required=True)
    n.add_argument("--epic", required=True)
    n.add_argument("--title", default="New Feature Specification")
    n.add_argument("--task")
    n.add_argument("--owner", default="Agent-A")
    ad = sub.add_parser("adopt")
    ad.add_argument("--id", required=True)
    ad.add_argument("--path", required=True, help="遗留 SPEC 文件的仓库相对路径")
    ad.add_argument("--epic", required=True)
    ad.add_argument("--title")
    ad.add_argument("--risk", default="HIGH")
    t = sub.add_parser("transition")
    t.add_argument("spec")
    t.add_argument("to")
    t.add_argument("--note")
    sg = sub.add_parser("signoff")
    sg.add_argument("--spec", required=True)
    sg.add_argument("--kind", choices=["design", "release"], required=True)
    sg.add_argument("--by", required=True)
    sg.add_argument("--ref", required=True, help="PR / Issue / 评审记录的可核验引用")
    ev = sub.add_parser("evidence")
    ev.add_argument("--spec", required=True)
    ev.add_argument("--class", dest="cls", required=True)
    ev.add_argument("--path", required=True, help="沙箱内的相对路径")
    ev.add_argument("--result", choices=["pass", "fail"], required=True)
    ev.add_argument("--note")
    un = sub.add_parser("unit")
    un.add_argument("--spec", required=True)
    un.add_argument("--unit", required=True)
    un.add_argument("--status", choices=["verified", "pending"], default="verified")
    at = sub.add_parser("attach")
    at.add_argument("--epic", required=True)
    at.add_argument("--spec", required=True)
    at.add_argument("--force", action="store_true")
    at.add_argument("--takeover", action="store_true")
    for name in ("check-scope", "heartbeat"):
        sub.add_parser(name).add_argument("--spec", required=True)
    sub.add_parser("conflicts").add_argument("--spec")
    sub.add_parser("finish").add_argument("--epic", required=True)
    sub.add_parser("status")
    sub.add_parser("overview")
    sub.add_parser("related").add_argument("--spec", required=True)
    sub.add_parser("precommit")
    ih = sub.add_parser("install-hooks")
    ih.add_argument("--force", action="store_true")
    ih.add_argument("--remove", action="store_true")
    ex = sub.add_parser("export-registry")
    ex.add_argument("--out")
    a = p.parse_args()
    a.model = FAMILY_ALIASES.get(a.model.lower(), a.model.lower())
    if a.model != "unknown" and a.model not in FAMILIES:
        die(f"--model 必须是 {sorted(FAMILIES)} 之一(或 unknown), 收到 {a.model!r}")
    lock = None if a.cmd in READONLY else acquire_lock()  # noqa: F841 (持有到进程结束)
    globals()["cmd_" + a.cmd.replace("-", "_").replace("export_registry", "export")](a)


if __name__ == "__main__":
    main()
