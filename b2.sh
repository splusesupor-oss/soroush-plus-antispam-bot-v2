#!/usr/bin/env bash
# ------------------------------------------------------------------
# b2 — لانچر قطعی ربات ۲ (bot2)
#
# فقط bot2 را اجرا می‌کند:
#   * BOT_INSTANCE=bot2 قبل از هر import قطعی می‌شود
#   * نشانگر clone (‎.bot_instance = bot2) بررسی/مهر می‌شود
#   * DATA_DIR اختصاصی: ~/.local/share/soroush-bot-bot2/
#   * PID اختصاصی:      ~/.local/share/soroush-bot-bot2/config/bot.pid
#   * هیچ فایل/پروسه‌ای از main یا bot3 لمس نمی‌شود
#
# استفاده:
#   b2            → اجرای bot2 با Watchdog (پیشنهادی، ری‌استارت خودکار)
#   b2 direct     → اجرای مستقیم bot2 بدون Watchdog
#   b2 stop       → توقف فقط bot2 (watchdog + پروسه‌ی فرزند خودش)
#   b2 status     → وضعیت bot2
#   b2 doctor     → بررسی جداسازی مسیرها + سلامت لاگ
#   b2 backup     → بکاپ دستی B2
# ------------------------------------------------------------------
set -u

BOT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT2_DATA="${SOROUSH_BOT_DATA_DIR_BOT2:-$HOME/.local/share/soroush-bot-bot2}"
MARKER="$BOT_ROOT/.bot_instance"
PIDFILE="$BOT2_DATA/config/bot.pid"
LOCKFILE="$BOT2_DATA/config/watchdog.lock"

cd "$BOT_ROOT" || { echo "❌ مسیر ربات ۲ پیدا نشد: $BOT_ROOT"; exit 1; }

# instance را برای کل زیر-پروسه‌ها قطعی کن — مستقل از .env و shell والد
export BOT_INSTANCE=bot2

# ---------------------------------------------------------------- guards
# ۱) نشانگر clone: اگر نیست، همین‌جا (فقط یک‌بار، به‌صورت آگاهانه) مهر می‌شود.
# ۲) اگر نشانگر با bot2 فرق دارد، ادامه نمی‌دهیم: یعنی این clone ربات دیگری است.
check_marker() {
  if [ -f "$MARKER" ]; then
    local current
    current="$(tr -d ' \t\r\n' < "$MARKER" 2>/dev/null || true)"
    if [ "$current" != "bot2" ]; then
      echo "=============================================================="
      echo " ⛔ توقف: این clone برای ربات دیگری مهر شده است."
      echo "    marker=$MARKER  →  مقدار فعلی: '$current'"
      echo "    اجرای bot2 در این مسیر باعث نوشتن در داده‌ی ربات دیگر می‌شد."
      echo "    اگر مطمئنی این clone واقعاً ربات ۲ است:"
      echo "      echo bot2 > \"$MARKER\""
      echo "=============================================================="
      return 2
    fi
    return 0
  fi
  printf 'bot2\n' > "$MARKER" 2>/dev/null || true
  chmod 600 "$MARKER" 2>/dev/null || true
  echo "ℹ️ نشانگر clone ساخته شد: $MARKER = bot2"
  return 0
}

# صاحب پروسه واقعاً همین clone است؟ (بدون اتکا به environ خام)
owned_by_this_clone() {
  local pid="$1" cwd="" line
  [ -n "$pid" ] && [ -d "/proc/$pid" ] || return 1
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
  if [ -n "$cwd" ] && [ "$cwd" = "$BOT_ROOT" ]; then
    return 0
  fi
  while IFS= read -r line; do
    case "$line" in
      *"$BOT_ROOT"*|*bot2.py*) return 0 ;;
      BOT_INSTANCE=bot2) return 0 ;;
    esac
  done < <( { tr '\0' '\n' < "/proc/$pid/cmdline" 2>/dev/null || true; \
              tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null || true; } )
  return 1
}

cmd="${1:-run}"

case "$cmd" in
  run|direct)
    check_marker || exit 2
    ;;
  *)
    ;;
esac

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
    if [ -f "$PIDFILE" ]; then
      pid="$(tr -d ' \t\r\n' < "$PIDFILE" 2>/dev/null || true)"
      if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
        if owned_by_this_clone "$pid"; then
          kill "$pid" && stopped=1 && echo "⏹ bot2 child متوقف شد (pid=$pid)"
        else
          echo "⚠️ pid=$pid متعلق به bot2 نیست؛ رد شد"
        fi
      fi
    fi
    # watchdog.lock خود bot2
    if [ -f "$LOCKFILE" ]; then
      wpid="$(python3 - "$LOCKFILE" <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("pid", ""))
except Exception:
    print("")
PY
)"
      if [ -n "$wpid" ] && kill -0 "$wpid" 2>/dev/null; then
        if owned_by_this_clone "$wpid"; then
          kill "$wpid" && stopped=1 && echo "⏹ bot2 watchdog متوقف شد (pid=$wpid)"
        else
          echo "⚠️ pid=$wpid متعلق به bot2 نیست؛ رد شد"
        fi
      fi
    fi
    [ "$stopped" = 0 ] && echo "ℹ️ پروسه‌ی در حال اجرایی برای bot2 پیدا نشد"
    ;;
  status)
    echo "BOT_ROOT   = $BOT_ROOT"
    echo "DATA_DIR   = $BOT2_DATA"
    echo "PID file   = $PIDFILE"
    if [ -f "$MARKER" ]; then
      echo "MARKER     = $(tr -d ' \t\r\n' < "$MARKER" 2>/dev/null)"
    else
      echo "MARKER     = (نبود — با اجرای بعدی ساخته می‌شود)"
    fi
    if [ -f "$PIDFILE" ]; then
      pid="$(tr -d ' \t\r\n' < "$PIDFILE" 2>/dev/null)"
      if kill -0 "$pid" 2>/dev/null; then
        echo "STATUS     = RUNNING (pid=$pid)"
      else
        echo "STATUS     = STOPPED (stale pid=$pid)"
      fi
    else
      echo "STATUS     = STOPPED"
    fi
    ;;
  doctor)
    check_marker
    echo "--- effective paths (اجرای واقعی، نه کامنت) ---"
    BOT_INSTANCE=bot2 python3 - <<'PY'
import json, os
os.environ["BOT_INSTANCE"] = "bot2"
from modules import instance_guard
from modules import runtime_paths
info = runtime_paths.describe()
print(json.dumps(info, ensure_ascii=False, indent=2))
try:
    instance_guard.assert_data_dir_is_own(info["instance"], info["data_dir"])
    print("ISOLATION  = OK  (data_dir متعلق به همین instance است)")
except instance_guard.InstanceConflict as error:
    print("ISOLATION  = FAIL")
    print(error)
PY
    echo "--- log health ---"
    python3 tools/log_health.py || true
    ;;
  backup)
    exec python3 tools/b2_backup.py backup "${@:2}"
    ;;
  *)
    echo "استفاده: b2 [run|direct|stop|status|doctor|backup]"
    exit 1
    ;;
esac
