#!/usr/bin/env bash
# worktree-setup.sh — 进入 git worktree 后执行一次。
#
# 通过 symlink 连接主 checkout 的 backend/.env，避免重复创建配置。
# 主 checkout 的 .env 是配置来源；JWT_SECRET / ENCRYPTION_KEYS / DATABASE_URL
# 必须一致，才能共享会话并解密已有 credential。
#
# 使用示例（在 worktree 中）：
#   bash scripts/worktree-setup.sh
#
# 幂等操作，可重复执行。

set -euo pipefail

# 检查当前 cwd 是否位于 git worktree。
toplevel=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [[ -z "$toplevel" ]]; then
  echo "✗ 当前目录不是 git repository。请进入 worktree 后重试。" >&2
  exit 1
fi

# 主 checkout 路径：git worktree list 的第一项（bare/main）。
# 通常第一个未标记 prunable 的项目就是主 checkout。
main_path=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
if [[ -z "$main_path" ]]; then
  echo "✗ 'git worktree list' 返回空结果。" >&2
  exit 1
fi

if [[ "$main_path" == "$toplevel" ]]; then
  echo "ℹ 当前为主 checkout，无需设置 symlink。"
  exit 0
fi

main_env="$main_path/backend/.env"
worktree_env="$toplevel/backend/.env"

if [[ ! -f "$main_env" ]]; then
  echo "✗ 主 checkout 缺少 backend/.env：$main_env" >&2
  echo "  请先在主 checkout 执行 'cp backend/.env.example backend/.env' 并填写 JWT_SECRET / ENCRYPTION_KEYS。" >&2
  exit 1
fi

# 若已有 .env 是普通文件，说明用户创建了 worktree 本地配置。
# 为避免冲突，先备份再替换为 symlink。
if [[ -f "$worktree_env" && ! -L "$worktree_env" ]]; then
  backup="$worktree_env.bak-$(date +%s)"
  echo "⚠ 已有 backend/.env 是普通文件，将备份到 $backup 后替换为 symlink。"
  mv "$worktree_env" "$backup"
fi

# 使用相对 symlink；只要主 checkout 未移动，就能从任意 worktree
# 准确指向主 checkout 的 backend/.env。
mkdir -p "$(dirname "$worktree_env")"
rel_target=$(python3 -c "import os.path; print(os.path.relpath('$main_env', start='$(dirname "$worktree_env")'))")
ln -sf "$rel_target" "$worktree_env"

# 验证结果。
if [[ ! -f "$worktree_env" ]]; then
  echo "✗ symlink 无法解析：$(readlink "$worktree_env")" >&2
  exit 1
fi

echo "✓ backend/.env → $(readlink "$worktree_env")"
echo "  resolved → $(python3 -c "import os; print(os.path.realpath('$worktree_env'))")"

# --- ADR-018 — backend/data symlink ---------------------------------------
# DB 与主 checkout 共享，但若各 worktree 使用独立的 backend/data/，
# publish/install 只会在 worktree 中生成正文文件。2026-05-23 曾发生清理
# worktree 后 DB 保留 row、文件却丢失的问题。对 data/ 采用与 .env 相同的
# symlink 方式，直接指向主 checkout 的 backend/data。
main_data="$main_path/backend/data"
worktree_data="$toplevel/backend/data"

mkdir -p "$main_data"

# 若 worktree 已有普通目录，仅在为空时自动移除并创建 symlink。
# 若包含数据，可能是用户在 worktree 中 publish/install 的结果。
# 为避免误删，仅输出手动处理说明。
if [[ -d "$worktree_data" && ! -L "$worktree_data" ]]; then
  if [[ -z "$(ls -A "$worktree_data" 2>/dev/null)" ]]; then
    rmdir "$worktree_data"
  else
    backup="$worktree_data.bak-$(date +%s)"
    echo
    echo "⚠ 已有 backend/data/ 是普通目录，且包含数据。"
    echo "  worktree 数据与主 checkout 分离可能导致 storage_path 失效。"
    echo "  手动处理："
    echo "    1) 停止在 worktree 中运行的 dev server"
    echo "    2) mv '$worktree_data' '$backup'   # 备份"
    echo "    3) bash scripts/worktree-setup.sh   # 重新执行"
    echo
  fi
fi

if [[ ! -e "$worktree_data" ]]; then
  rel_data_target=$(python3 -c "import os.path; print(os.path.relpath('$main_data', start='$(dirname "$worktree_data")'))")
  ln -sf "$rel_data_target" "$worktree_data"
  echo "✓ backend/data → $(readlink "$worktree_data")"
elif [[ -L "$worktree_data" ]]; then
  echo "✓ backend/data → $(readlink "$worktree_data")（已为 symlink）"
fi

echo
echo "后续步骤："
echo "  1) 启动 backend：cd backend && uv run uvicorn app.main:app --reload --port 8001 --reload-dir app"
echo "     （--reload-dir app 避免 publish/install 时 data/ 变化触发 reload）"
echo "  2) 启动 frontend：cd frontend && pnpm dev"
echo
echo "说明：ADR-018 — storage_path 保存为相对于 settings.data_root 的路径。"
echo "       backend/data symlink 与相对路径字段共同保证清理 worktree 后"
echo "       主 checkout 的数据仍被保留。"
