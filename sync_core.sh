#!/bin/bash
# 从上游 alexbers/mtprotoproxy 同步核心逻辑到 core.py
# 用法: bash sync_core.sh [分支]   (默认 master)
set -e

REPO="https://raw.githubusercontent.com/alexbers/mtprotoproxy"
BRANCH="${1:-master}"
FILE="mtprotoproxy.py"
TARGET="core.py"

tmp=$(mktemp)
echo "Fetching ${REPO}/${BRANCH}/${FILE} ..."
curl -fsSL "${REPO}/${BRANCH}/${FILE}" -o "$tmp"
if [ ! -s "$tmp" ]; then
  echo "ERROR: fetch failed"
  rm -f "$tmp"
  exit 1
fi

# 上游文件为 MIT 许可，保留原版权与许可信息
cp "$tmp" "$TARGET"
rm -f "$tmp"
echo "core.py synced from upstream ${BRANCH}."
echo "Review changes before committing: git diff core.py"
