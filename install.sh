#!/usr/bin/env bash
# spec-registry 一键安装 (macOS / Linux / Windows Git Bash)
#
#   ./install.sh                      安装 skill 到 ~/.claude/skills/spec-registry
#   ./install.sh --init [DIR]         初始化项目(默认当前目录): 复制脚本、写协作纪律、装 pre-commit hook
#   ./install.sh --all  [DIR]         以上两步一起做
#   ./install.sh --uninstall [DIR]    卸载 skill; 带 DIR 时同时移除该项目的脚手架(保留 .specs 数据)
#
# 选项:
#   --skills-dir DIR     skill 安装目录, 默认 ~/.claude/skills
#   --with-ci            初始化时同时写 .github/workflows/spec_registry.yml
#   --install-deps       缺少 pyyaml 时自动 pip install --user pyyaml
#   --dry-run            只打印要做的事, 不改动任何文件
#   --from PATH          从本地目录或 .tar.gz 安装(离线)
#   --repo OWNER/REPO    远程安装来源, 或环境变量 SPEC_REGISTRY_REPO
#   --ref REF            远程分支/标签, 默认 main
#
# 远程一键安装(公开仓库):
#   curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh | bash -s -- --repo OWNER/REPO --all
# 私有仓库: 先 export GITHUB_TOKEN=<有 repo 读权限的 token>, 或直接 git clone 后本地运行。
set -euo pipefail

NAME="spec-registry"
MODE="skill"; DIR=""; SKILLS_DIR="${HOME}/.claude/skills"
WITH_CI=0; DEPS=0; DRY=0; FROM=""; REPO="${SPEC_REGISTRY_REPO:-}"; REF="main"; UNINSTALL=0

die()  { echo "[ERROR] $*" >&2; exit 1; }
info() { echo "[INFO] $*"; }
run()  { if [ "$DRY" = 1 ]; then echo "[DRY] $*"; else eval "$@"; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --init)        MODE="init"; if [ $# -gt 1 ] && [[ "$2" != --* ]]; then DIR="$2"; shift; fi ;;
    --all)         MODE="all";  if [ $# -gt 1 ] && [[ "$2" != --* ]]; then DIR="$2"; shift; fi ;;
    --uninstall)   UNINSTALL=1; if [ $# -gt 1 ] && [[ "$2" != --* ]]; then DIR="$2"; shift; fi ;;
    --skills-dir)  SKILLS_DIR="$2"; shift ;;
    --with-ci)     WITH_CI=1 ;;
    --install-deps) DEPS=1 ;;
    --dry-run)     DRY=1 ;;
    --from)        FROM="$2"; shift ;;
    --repo)        REPO="$2"; shift ;;
    --ref)         REF="$2"; shift ;;
    -h|--help)     sed -n '2,24p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "未知参数: $1 (用 --help 查看用法)" ;;
  esac
  shift
done

PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || die "需要 python3"

# ---------------------------------------------------------------- 定位来源
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
SRC=""; TMP=""
cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; return 0; }
trap cleanup EXIT

if [ "$UNINSTALL" = 0 ]; then
  if [ -n "$FROM" ]; then
    if [ -d "$FROM" ]; then SRC="$(cd "$FROM" && pwd)"
    else
      TMP="$(mktemp -d)"; tar -xzf "$FROM" -C "$TMP"
      SRC="$(dirname "$(find "$TMP" -maxdepth 3 -type d -name skills | head -1)")"
    fi
  elif [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/skills/$NAME/SKILL.md" ]; then
    SRC="$SELF_DIR"
  elif [ -n "$REPO" ]; then
    command -v curl >/dev/null || die "远程安装需要 curl"
    TMP="$(mktemp -d)"
    info "下载 $REPO@$REF ..."
    if [ -n "${GITHUB_TOKEN:-}" ]; then
      curl -fsSL -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/$REPO/tarball/$REF" -o "$TMP/src.tgz" || die "下载失败(检查仓库名、分支和 token 权限)"
    else
      curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" -o "$TMP/src.tgz" \
        || die "下载失败。私有仓库请设置 GITHUB_TOKEN, 或先 git clone 再本地运行"
    fi
    tar -xzf "$TMP/src.tgz" -C "$TMP"
    SRC="$(dirname "$(find "$TMP" -maxdepth 3 -type d -name skills | head -1)")"
  else
    die "找不到安装来源: 请在仓库目录里运行, 或用 --from / --repo 指定"
  fi
  [ -f "$SRC/skills/$NAME/SKILL.md" ] || die "来源里没有 skills/$NAME/SKILL.md: $SRC"
fi

# ---------------------------------------------------------------- 工具函数
upsert_block() {   # $1=目标文件 $2=块文件
  "$PY" - "$1" "$2" <<'PYEOF'
import re, sys, pathlib
f, blk = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]).read_text("utf-8").strip()
B, E = "<!-- spec-registry:begin -->", "<!-- spec-registry:end -->"
txt = f.read_text("utf-8") if f.exists() else ""
if B in txt and E in txt:
    txt = re.sub(re.escape(B) + r".*?" + re.escape(E), lambda m: blk, txt, flags=re.S)
else:
    txt = (txt.rstrip() + "\n\n" if txt.strip() else "") + blk + "\n"
f.parent.mkdir(parents=True, exist_ok=True)
f.write_text(txt, "utf-8")
PYEOF
}

remove_block() {   # $1=文件 $2=起始标记 $3=结束标记, 标记之间的内容全部移除
  "$PY" - "$1" "$2" "$3" <<'PYEOF'
import re, sys, pathlib
f, B, E = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
if not f.exists():
    sys.exit(0)
txt = f.read_text("utf-8")
new = re.sub(r"\n*" + re.escape(B) + r".*?" + re.escape(E) + r"\n*", "\n", txt, flags=re.S).strip()
if new:
    f.write_text(new + "\n", "utf-8")
else:
    f.unlink()
PYEOF
}

check_deps() {
  if ! "$PY" -c "import yaml" 2>/dev/null; then
    if [ "$DEPS" = 1 ]; then run "\"$PY\" -m pip install --user pyyaml"
    else echo "[WARN] 缺少 pyyaml: 请运行  $PY -m pip install --user pyyaml  (或加 --install-deps 重跑)"; fi
  fi
}

# ---------------------------------------------------------------- 安装 skill
install_skill() {
  local dest="$SKILLS_DIR/$NAME"
  info "安装 skill -> $dest"
  run "mkdir -p \"$SKILLS_DIR\" && rm -rf \"$dest\" && cp -R \"$SRC/skills/$NAME\" \"$dest\""
  run "chmod +x \"$dest\"/scripts/*.sh \"$dest\"/scripts/*.py 2>/dev/null || true"
}

# ---------------------------------------------------------------- 初始化项目
init_project() {
  local top
  top="$(git -C "${DIR:-.}" rev-parse --show-toplevel 2>/dev/null)" || die "${DIR:-.} 不是 git 仓库"
  # 在 worktree 里运行时, 回到主工作区
  local common; common="$(cd "$top" && cd "$(git rev-parse --git-common-dir)" && pwd)"
  top="$(dirname "$common")"
  info "初始化项目: $top"
  local s="$SRC/skills/$NAME"
  run "mkdir -p \"$top/scripts/spec-registry\" \"$top/.specs\""
  run "cp -R \"$s/scripts/.\" \"$top/scripts/spec-registry/\""
  run "chmod +x \"$top/scripts/spec-registry/\"*.sh \"$top/scripts/spec-registry/\"*.py 2>/dev/null || true"
  [ -e "$top/.specs/.gitkeep" ] || run "touch \"$top/.specs/.gitkeep\""

  # .gitattributes: 固定 LF, 避免 Windows autocrlf 改变 SPEC 哈希
  if [ "$DRY" = 1 ]; then echo "[DRY] 更新 $top/.gitattributes"
  else
    "$PY" - "$top/.gitattributes" "$s/templates/gitattributes.txt" <<'PYEOF'
import re, sys, pathlib
f, blk = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]).read_text("utf-8").strip()
B, E = "# spec-registry managed begin", "# spec-registry managed end"
txt = f.read_text("utf-8") if f.exists() else ""
if B in txt and E in txt:
    txt = re.sub(re.escape(B) + r".*?" + re.escape(E), lambda m: blk, txt, flags=re.S)
else:
    txt = (txt.rstrip() + "\n\n" if txt.strip() else "") + blk + "\n"
f.write_text(txt, "utf-8")
PYEOF
  fi

  # 协作纪律: AGENTS.md 一定写; CLAUDE.md 只在已存在时写
  local rf
  for rf in "$top/AGENTS.md" "$top/CLAUDE.md" "$top/.claude/CLAUDE.md"; do
    if [ "$rf" = "$top/AGENTS.md" ] || [ -f "$rf" ]; then
      info "写入协作纪律 -> ${rf#$top/}"
      if [ "$DRY" = 1 ]; then echo "[DRY] upsert $rf"; else upsert_block "$rf" "$s/templates/rules-block.md"; fi
    fi
  done

  if [ "$WITH_CI" = 1 ]; then
    run "mkdir -p \"$top/.github/workflows\" && cp \"$s/templates/spec_registry.workflow.yml\" \"$top/.github/workflows/spec_registry.yml\""
    info "已写入 .github/workflows/spec_registry.yml"
  fi
  [ -f "$top/.github/CODEOWNERS" ] || info "提示: 参考 skills/$NAME/templates/CODEOWNERS.example 配置 CODEOWNERS + 受保护分支, 人类签发才有约束力"

  info "安装 pre-commit hook"
  if [ "$DRY" = 1 ]; then echo "[DRY] workspace.py install-hooks"
  else (cd "$top" && "$PY" scripts/spec-registry/workspace.py install-hooks) || echo "[WARN] hook 未安装(可能已有自定义 pre-commit), 见上面的提示"; fi

  echo
  info "完成。请提交这些文件: scripts/spec-registry/  .specs/  AGENTS.md  .gitattributes"
  info "下一步: 在每个 Agent 会话里设置 SPEC_ROLE / SPEC_AGENT / SPEC_MODEL, 然后 ./scripts/spec-registry/workspace.sh --help"
}

# ---------------------------------------------------------------- 卸载
uninstall() {
  info "移除 skill: $SKILLS_DIR/$NAME"
  run "rm -rf \"$SKILLS_DIR/$NAME\""
  if [ -n "$DIR" ]; then
    local top; top="$(git -C "$DIR" rev-parse --show-toplevel 2>/dev/null)" || die "$DIR 不是 git 仓库"
    local common; common="$(cd "$top" && cd "$(git rev-parse --git-common-dir)" && pwd)"; top="$(dirname "$common")"
    info "移除项目脚手架: $top (保留 .specs 里的 SPEC 数据)"
    if [ -f "$top/scripts/spec-registry/workspace.py" ] && [ "$DRY" = 0 ]; then
      (cd "$top" && "$PY" scripts/spec-registry/workspace.py install-hooks --remove) || true
    fi
    local rf
    for rf in "$top/AGENTS.md" "$top/CLAUDE.md" "$top/.claude/CLAUDE.md"; do
      [ -f "$rf" ] && { if [ "$DRY" = 1 ]; then echo "[DRY] 移除 $rf 里的纪律块"; else remove_block "$rf" "<!-- spec-registry:begin -->" "<!-- spec-registry:end -->"; fi; }
    done
    [ -f "$top/.gitattributes" ] && { if [ "$DRY" = 1 ]; then echo "[DRY] 移除 .gitattributes 块"; else remove_block "$top/.gitattributes" "# spec-registry managed begin" "# spec-registry managed end"; fi; }
    run "rm -rf \"$top/scripts/spec-registry\" && rmdir \"$top/scripts\" 2>/dev/null || true"
    run "rm -f \"$top/.github/workflows/spec_registry.yml\""
  fi
  info "卸载完成。运行状态在 .git/spec-registry/, 需要的话请手动删除。"
}

# ---------------------------------------------------------------- 主流程
if [ "$UNINSTALL" = 1 ]; then uninstall; exit 0; fi
check_deps
case "$MODE" in
  skill) install_skill ;;
  init)  init_project ;;
  all)   install_skill; init_project ;;
esac
