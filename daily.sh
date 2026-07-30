#!/bin/bash
# 每日自动抓取阳光家缘官方数据 -> 归档 -> 重新生成网站 -> 推送到 GitHub Pages 仓库
LOG=/workspace/daily.log
exec > >(tee -a "$LOG") 2>&1

echo "=== daily.sh started at $(date -Iseconds) ==="
cd /workspace || { echo "ERROR: cannot cd /workspace"; exit 1; }

echo "[1/4] fetching..."
python3.11 scraper.py || { echo "ERROR: scraper failed"; exit 1; }

echo "[2/4] building site..."
python3.11 build_site.py || { echo "ERROR: build_site failed"; exit 1; }

echo "[3/4] copying index.html for Pages..."
cp "广州新房网签数据.html" index.html || { echo "ERROR: copy failed"; exit 1; }

echo "[4/4] git commit & push..."
if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && git remote get-url origin >/dev/null 2>&1; then
  git add -A
  git commit -m "daily update $(date +%F)" || echo "WARN: nothing to commit"
  git push origin main || echo "WARN: git push failed"
else
  echo "WARN: no git remote, skipping push"
fi

echo "=== daily.sh finished at $(date -Iseconds) ==="
