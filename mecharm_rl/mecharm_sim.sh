#!/usr/bin/env bash
# =============================================================================
# mecharm_sim.sh — mecharm 6軸アーム 可視化シミュレーション(疑似3D)の起動スクリプト
#   分散Xinu(12) + Capability推論 + TinyML強化学習 の可視化画面をブラウザで開く。
#
# 使い方:
#   ./mecharm_sim.sh          … サーバ起動 + ブラウザで画面を開く(既定)
#   ./mecharm_sim.sh start    … サーバ起動 + 画面を開く
#   ./mecharm_sim.sh open     … 画面をブラウザで開くだけ(起動済みなら)
#   ./mecharm_sim.sh stop     … サーバ停止
#   ./mecharm_sim.sh status   … 稼働状態を表示
# =============================================================================
set -euo pipefail

PORT=8021
FILE="mecharm_sim.html"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # このスクリプトのある場所
URL="http://127.0.0.1:${PORT}/${FILE}"
LOG="${DIR}/.mecharm_sim.log"

is_up() { curl -s -o /dev/null -w '%{http_code}' "$URL" 2>/dev/null | grep -q 200; }

open_browser() {
  if command -v open >/dev/null 2>&1;      then open "$URL"          # macOS
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"     # Linux
  else echo "ブラウザで開いてください: $URL"; fi
}

start() {
  if is_up; then
    echo "[mecharm] 既に稼働中 → $URL"
  else
    echo "[mecharm] サーバ起動中 (port ${PORT}) …"
    ( cd "$DIR" && nohup python3 -m http.server "$PORT" --bind 127.0.0.1 >"$LOG" 2>&1 & )
    for _ in 1 2 3 4 5 6 7 8 9 10; do is_up && break; sleep 0.3; done
    is_up && echo "[mecharm] 起動 → $URL" || { echo "[mecharm] 起動失敗。ログ: $LOG"; exit 1; }
  fi
  open_browser
}

case "${1:-start}" in
  start|"") start ;;
  open)     is_up && open_browser || { echo "[mecharm] 未起動です。'./mecharm_sim.sh start' で起動してください"; exit 1; } ;;
  stop)     lsof -ti:"$PORT" | xargs kill -9 2>/dev/null && echo "[mecharm] 停止しました" || echo "[mecharm] 稼働中のサーバはありません" ;;
  status)   is_up && echo "[mecharm] 稼働中 → $URL" || echo "[mecharm] 停止" ;;
  *)        echo "使い方: $0 {start|open|stop|status}"; exit 1 ;;
esac
