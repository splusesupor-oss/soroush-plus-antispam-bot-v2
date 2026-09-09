#!/usr/bin/env bash
# ------------------------------------------------------------------
# b2 — لانچر قطعی ربات ۲ (bot2)
#
# فقط bot2 را اجرا می‌کند:
#   * BOT_INSTANCE=bot2 قبل از هر import قطعی می‌شود
#   * DATA_DIR اختصاصی: ~/.local/share/soroush-bot-bot2/
#   * PID اختصاصی:      ~/.local/share/soroush-bot-bot2/config/bot.pid
#   * هیچ فایل/پروسه‌ای از main یا bot3 لمس نمی‌شود
#
# استفاده:
#   b2            → اجرای bot2 با Watchdog (پیشنهادی، ری‌استارت خودکار)
#   b2 direct     → اجرای مستقیم bot2 بدون Watchdog
#   b2 stop       → توقف فقط bot2 (watchdog + پروسه‌ی فرزند خودش)
#   b2 status     → وضعیت bot2
# ------------------------------------------------------------------
set -u
BOT2_DIR="$HOME/soroush-plus-antispam-bot-old-2"
BOT2_DATA="$HOME/.local/share/soroush-bot-bot2"
cd "$BOT2_DIR" || { echo "❌ مسیر ربات ۲ پیدا نشد: $BOT2_DIR"; exit 1; }

# instance را برای کل زیر-پروسه‌ها قطعی کن — مستقل از .env و shell والد
export BOT_INSTANCE=bot2

cmd="${1:-run}"

case "$cmd" in
  run)
    exec python3 watchdog.py --replace
    ;;
  direct)
    exec python3 bot2.py
    ;;
  stop)
    stopped=0
    # فقط PIDهای ثبت‌شده در runtime خود bot2؛ به main/bot3 دست نمی‌زنیم.
    for pidfile in "$BOT2_DATA/config/bot.pid"; do
      if [ -f "$pidfile" ]; then
        pid="$(cat "$pidfile" 2>/dev/null)"
        if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
          # اطمینان: فقط اگر پروسه واقعاً متعلق به این clone باشد
          if grep -qa "soroush-plus-antispam-bot-old-2\|BOT_INSTANCE=bot2" \
              "/proc/$pid/cmdline" "/proc/$pid/environ" 2>/dev/null; then
            kill "$pid" && stopped=1 && echo "⏹ bot2 child متوقف شد (pid=$pid)"
          else
            echo "⚠️ pid=$pid متعلق به bot2 نیست؛ رد شد"
          fi
        fi
      fi
    done
    # watchdog.lock خود bot2
    lock="$BOT2_DATA/config/watchdog.lock"
    if [ -f "$lock" ]; then
      wpid="$(python3 - "$lock" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("pid", ""))
except Exception:
    print("")
PY
)"
      if [ -n "$wpid" ] && kill -0 "$wpid" 2>/dev/null; then
        if grep -qa "soroush-plus-antispam-bot-old-2\|BOT_INSTANCE=bot2" \
            "/proc/$wpid/cmdline" "/proc/$wpid/environ" 2>/dev/null; then
          kill "$wpid" && stopped=1 && echo "⏹ bot2 watchdog متوقف شد (pid=$wpid)"
        fi
      fi
    fi
    [ "$stopped" = 0 ] && echo "ℹ️ پروسه‌ی در حال اجرایی برای bot2 پیدا نشد"
    ;;
  status)
    echo "BOT2_DIR   = $BOT2_DIR"
    echo "DATA_DIR   = $BOT2_DATA"
    echo "PID file   = $BOT2_DATA/config/bot.pid"
    if [ -f "$BOT2_DATA/config/bot.pid" ]; then
      pid="$(cat "$BOT2_DATA/config/bot.pid")"
      if kill -0 "$pid" 2>/dev/null; then
        echo "STATUS     = RUNNING (pid=$pid)"
      else
        echo "STATUS     = STOPPED (stale pid=$pid)"
      fi
    else
      echo "STATUS     = STOPPED"
    fi
    ;;
  *)
    echo "استفاده: b2 [run|direct|stop|status]"
    exit 1
    ;;
esac
