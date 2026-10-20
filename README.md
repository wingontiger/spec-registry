# spec-registry

多 Agent / 多任务并行开发的 **SPEC 治理 + git worktree 协调** skill。

解决的问题:同一个项目里有多个任务、多个 Agent 同时发 SPEC、改代码,彼此看不到对方在改什么,到合并时才发现接口或数据表冲突;worktree 越开越多;"测试通过"被当成"验收通过";模型给自己的工作签发通过。

它把这些做成确定性的命令行门禁,Agent 只能调命令,不能自己建分支、自己改状态、自己签发。

## 一分钟上手

```bash
# 1. 克隆本仓库(私有仓库用你自己的地址)
git clone <你的仓库地址> spec-registry-skill && cd spec-registry-skill

# 2. 一键安装: 装 skill + 初始化你的项目
./install.sh --all /path/to/your/project

# 3. 缺 pyyaml 时
python3 -m pip install --user pyyaml        # 或给 install.sh 加 --install-deps
```

之后每个 Agent 会话开始前设置三个环境变量:

```bash
export SPEC_ROLE=C          # A 设计 / B 验证 / C 开发 / D 审核 / H 人类
export SPEC_AGENT=glm-1     # 你给这个会话起的名字
export SPEC_MODEL=glm       # glm / gemini / claude / gpt / deepseek
```

Windows 用 Git Bash 运行 `install.sh`;或在 PowerShell 里运行 `install.ps1`(**未在 Windows 实机验证过,请先加 `-DryRun`**)。

## 安装方式

| 目的 | 命令 |
|---|---|
| 只装 skill(Claude Code 用户级) | `./install.sh` → `~/.claude/skills/spec-registry` |
| 只装到某个项目里的 skill 目录 | `./install.sh --skills-dir /项目/.claude/skills` |
| 初始化项目 | `./install.sh --init /path/to/project` |
| 两步一起 | `./install.sh --all /path/to/project` |
| 同时写 GitHub Actions | 加 `--with-ci` |
| 先看会做什么 | 加 `--dry-run` |
| 离线(压缩包/目录) | `./install.sh --from spec-registry-skill.tar.gz --all DIR` |
| 远程一键(公开仓库) | `curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh \| bash -s -- --repo OWNER/REPO --all` |
| 远程一键(私有仓库) | `export GITHUB_TOKEN=<token>` 后同上,或直接 git clone 后本地运行 |
| 卸载 | `./install.sh --uninstall [项目目录]`(保留 `.specs/` 数据) |

`--init` 对项目做了什么(不会自动 commit,你自己提交):

- `scripts/spec-registry/`:复制 CLI(`workspace.py`、`workspace.sh`、`workspace.cmd`、冒烟测试、CI 检查器)。脚本随项目入库,所有 Agent 和 CI 用同一份。
- `.specs/`:SPEC 存放目录。
- `AGENTS.md`:追加协作纪律块(用 `<!-- spec-registry:begin/end -->` 标记,重跑只会更新这一块)。`CLAUDE.md`、`.claude/CLAUDE.md` 已存在时也会写入。Cursor、Codex、Antigravity 等读 `AGENTS.md` 的工具因此无需 skill 也能遵守纪律。
- `.gitattributes`:固定 `.specs/` 等文件为 LF,避免 Windows `autocrlf` 改变 SPEC 哈希。
- `.git/hooks/pre-commit`:Epic 沙箱里的提交,暂存文件越出 `impact_scope` 会被拦截;没有已认领 SPEC 的孤儿沙箱也会被拦截。已有自定义 hook 时不会覆盖。

## 日常流程

```
A 设计 ─ new-spec ─→ 填 impact_scope / risk ─→ 提交到主分支 ─→ transition verifying_spec
B 验证 ─ transition reviewing_spec (full 轨道) 或 approved (lite 轨道)
D 审核 ─ transition approved                      ← full 轨道还需要人类 signoff
C 开发 ─ attach ─→ 在 .worktrees/epic-<e>/ 里改 ─→ check-scope ─→ transition verifying_impl
B 验证 ─ evidence 登记证据 ─→ transition reviewing_impl
D 审核 ─ (合并分支) ─→ finish
```

一个完整示例(全部通过 `./scripts/spec-registry/workspace.sh`):

```bash
W=./scripts/spec-registry/workspace.sh

# A: 起草(在主分支)
SPEC_ROLE=A SPEC_MODEL=claude $W new-spec --id SPEC-012 --epic order --title "订单超时自动取消"
#   编辑 .specs/SPEC-012.md: impact_scope.files、risk、required_evidence ...
git add .specs && git commit -m "SPEC-012 draft"
SPEC_ROLE=A SPEC_MODEL=claude $W transition SPEC-012 verifying_spec

# B → D: 验证与审核(HIGH 风险走 full 轨道,D 必须与 A/C 不同底座)
SPEC_ROLE=B SPEC_MODEL=gpt    $W transition SPEC-012 reviewing_spec
SPEC_ROLE=H $W signoff --spec SPEC-012 --kind design --by <你> --ref PR#41
SPEC_ROLE=D SPEC_MODEL=gemini $W transition SPEC-012 approved

# C: 开发
SPEC_ROLE=C SPEC_AGENT=glm-1 SPEC_MODEL=glm $W attach --epic order --spec SPEC-012
#   进入输出的 .worktrees/epic-order/ 改代码并 commit
$W check-scope --spec SPEC-012
SPEC_ROLE=C SPEC_MODEL=glm $W transition SPEC-012 verifying_impl

# B: 登记证据并推进
SPEC_ROLE=B SPEC_MODEL=gpt $W evidence --spec SPEC-012 --class unit --path tests/test_order.py --result pass
SPEC_ROLE=B SPEC_MODEL=gpt $W transition SPEC-012 reviewing_impl

# 合并分支 → H 发布签发(HIGH/CRITICAL)→ D 收尾
git merge --no-ff epic/order
SPEC_ROLE=H $W signoff --spec SPEC-012 --kind release --by <你> --ref PR#52
SPEC_ROLE=D SPEC_MODEL=gemini $W finish --epic order
```

小改动(LOW/MEDIUM 风险)把 SPEC 里的 `track` 改成 `lite`:跳过 D 设计审核和人类签发,B 直接 `approved`。

## 命令速查

| 命令 | 角色 | 作用 |
|---|---|---|
| `new-spec --id --epic --title` | A | 生成 SPEC 模板并登记 |
| `adopt --id --path --epic --risk` | A | 把已有的遗留 SPEC 登记为 `discovered`,不改原文件 |
| `transition <ID> <状态>` | 按状态机 | 状态流转,带门禁检查 |
| `signoff --spec --kind design\|release --by --ref` | H | 人类签发 |
| `attach --epic --spec [--takeover] [--force]` | C | 认领,创建或复用 Epic 沙箱 |
| `heartbeat --spec` | C | 续租(默认 4 小时) |
| `evidence --spec --class --path --result` | B/C/D | 登记验证证据,绑定当前提交 |
| `unit --spec --unit U1` | B | 标记 SPEC 内某个单元已验证 |
| `check-scope --spec` | 任何 | 校验自认领以来的全部改动是否在 `impact_scope` 内 |
| `conflicts [--spec]` | 任何 | 列出范围冲突 |
| `overview` | 任何 | L0 总览:一行一个 SPEC,适合注入 Agent 上下文 |
| `related --spec` | 任何 | L1:只加载与该 SPEC 相关的(依赖、同 Epic、范围重叠) |
| `finish --epic` | D | 终审收尾,清理沙箱 |
| `export-registry --out registry/spec_registry.json` | 任何 | 导出入库的治理索引 |
| `install-hooks [--remove]` | 任何 | 安装/移除 pre-commit hook |
| `status` | 任何 | 看板 + worktree 列表 |

## 治理索引与 CI

`export-registry` 把运行时状态导出成 `registry/spec_registry.json`(入库)。`scripts/spec-registry/ci/spec_registry.py` 可在 CI 校验它(哈希是否漂移、批准字段是否齐全、证据文件是否存在)。`--with-ci` 会写入 `.github/workflows/spec_registry.yml`,其中还包含孤儿 Epic 分支检查。

**人类签发的约束力不来自脚本**。`signoff` 只记录文本,谁都能填。要让它真正有效,请在 GitHub 里配置受保护分支 + CODEOWNERS(示例:`skills/spec-registry/templates/CODEOWNERS.example`),并让 `registry/` 和 `.specs/` 只能经 PR 变更。

## 和 peer-relay 的关系

spec-registry 管"改什么、在哪改、谁批准"(静态契约 + 沙箱)。跨会话接力和实时心跳(`.sync/`、UAS)属于 peer-relay,两者分开:peer-relay 只读 `<git common dir>/spec-registry/registry.json`,spec-registry 不依赖 peer-relay。

## 设计取舍(详见 docs/DESIGN.md)

- 运行时状态存在 `.git/spec-registry/`,不入库:不会因为各分支重复生成而合并冲突,代价是单机方案。入库的只有 SPEC 和治理索引。
- 一个 Epic 沙箱同一时间只承载一个活跃 SPEC,沙箱上限 5 个。
- 没有做 MCP server:这些 Agent 都有 shell,命令行已足够;MCP 会多一个常驻进程和一套接口要维护。需要时再加一层很薄的封装。

## 已知局限

- 脚本无法鉴别身份:`SPEC_ROLE`、`--as`、`--model` 都靠自觉填写。
- 证据只证明"有人登记过一次通过",不证明测试质量,也不证明测试真的跑过。
- `risk` 由 A 填写,标低可以躲过人类签发,需要 D 或 H 抽查。
- 不检查函数级冲突;`modules` 比 `files` 粗,建议默认只写 `files`。
- Windows 文件锁分支和 `install.ps1` 没有在真实 Windows 上验证。
- 不实现 `provides/consumes` 接口联动,不执行缺陷规则(DL-xx)。

## 开发与测试

```bash
bash skills/spec-registry/scripts/smoke-test.sh     # 61 项检查,在临时仓库里跑完整流程
```

要求:Python 3、pyyaml、git。

## License

[MIT](LICENSE)。
