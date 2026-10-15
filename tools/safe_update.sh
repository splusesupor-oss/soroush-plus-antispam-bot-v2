#!/usr/bin/env bash
# ------------------------------------------------------------------
# safe_update.sh — به‌روزرسانی ایمن این clone از گیت‌هاب
#
# چرا لازم است؟
# تا پیش از این، فایل `.env` در گیت track شده بود. حالا که از فهرست خارج
# شده، یک `git pull` معمولی می‌تواند فایل `.env` را از دیسک شما هم پاک کند؛
# یعنی ربات سشن خودش را از دست می‌دهد. این اسکریپت قبل از pull از همه‌ی
# فایل‌های حساس نسخه‌ی امن می‌گیرد، pull را انجام می‌دهد و اگر چیزی گم شد
# همان‌جا برمی‌گرداند.
#
# استفاده:
#   bash tools/safe_update.sh              # pull از شاخه‌ی ردیابی‌شده
#   bash tools/safe_update.sh --branch NAME
#   bash tools/safe_update.sh --dry-run    # فقط بکاپ و نمایش وضعیت
# ------------------------------------------------------------------
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BRANCH=""
DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --branch) BRANCH="${2:-}"; shift 2 ;;
    --root) ROOT="$(cd "${2:-.}" && pwd)"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "استفاده: safe_update.sh [--branch NAME] [--root PATH] [--dry-run]"; exit 1 ;;
  esac
done

cd "$ROOT" || exit 1
git rev-parse --git-dir >/dev/null 2>&1 || { echo "❌ این مسیر مخزن گیت نیست: $ROOT"; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
SAFE="$HOME/.soroush-safe-update-$STAMP"
PROTECTED=".env .env.old .env.session_backup .env.before_fix .env.before_fi .env.backup_old_session .bot_instance"

mkdir -p "$SAFE" || { echo "❌ نتوانستم پوشه‌ی امن بسازم: $SAFE"; exit 1; }
chmod 700 "$SAFE" 2>/dev/null || true

echo "🔐 پوشه‌ی امن: $SAFE"
saved=0
for name in $PROTECTED; do
  if [ -f "$ROOT/$name" ]; then
    if cp -p "$ROOT/$name" "$SAFE/$name" 2>/dev/null; then
      chmod 600 "$SAFE/$name" 2>/dev/null || true
      saved=$((saved + 1))
      echo "   ✔ $name"
    fi
  fi
done
[ "$saved" -eq 0 ] && echo "   (فایل حساسی برای نگه‌داشتن پیدا نشد)"

# manifest + hashes so the restore can be verified, not guessed
( cd "$SAFE" && ls -1 > MANIFEST.txt 2>/dev/null; sha256sum .env 2>/dev/null > .env.sha256 || true )

if [ "$DRY_RUN" = 1 ]; then
  echo "ℹ️ --dry-run: هیچ pull انجام نشد."
  exit 0
fi

echo "⬇️  دریافت تغییرات..."
git fetch --all --prune || { echo "❌ fetch شکست خورد (شبکه/تأیید دسترسی)"; exit 2; }
if [ -n "$BRANCH" ]; then
  git checkout "$BRANCH" || exit 2
fi

# شاخه‌ی فعلی + تشخیص وجود upstream — یک کلون محلی اغلب upstream ندارد و
# git pull در آن با پیام «no tracking information» رد می‌شود.
CURRENT="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)"

if [ -z "$CURRENT" ]; then
  echo "❌ وضعیت گیت قابل تشخیص نیست."; exit 2
fi

if [ "$CURRENT" = "HEAD" ]; then
  echo "⚠️ در حالت detached HEAD هستید؛ ابتدا روی یک شاخه بروید:"
  echo "   git checkout -B $BRANCH origin/$BRANCH"
  exit 2
fi

pull_ok=0
if [ -n "$UPSTREAM" ]; then
  git pull --ff-only && pull_ok=1
else
  echo "ℹ️ شاخه‌ی «$CURRENT» upstream ندارد؛ از origin/$CURRENT استفاده می‌کنم."
  if git show-ref --verify --quiet "refs/remotes/origin/$CURRENT"; then
    git pull --ff-only origin "$CURRENT" && pull_ok=1
    # ثبت upstream برای دفعات بعد (بدون تغییر تاریخچه)
    git branch --set-upstream-to="origin/$CURRENT" "$CURRENT" >/dev/null 2>&1 || true
  fi
fi

if [ "$pull_ok" != 1 ]; then
  echo "❌ pull با --ff-only انجام نشد. هیچ داده‌ای تغییر نکرد."
  echo "   تشخیص: شاخه=$CURRENT upstream=${UPSTREAM:-<ندارد>}"
  echo "   اگر تغییرات محلی دارید: git status   (هیچ چیز خودکار پاک نشد)"
  echo "   نسخه‌ی امن فایل‌ها: $SAFE"
  exit 2
fi

restored=0
for name in $PROTECTED; do
  if [ ! -f "$ROOT/$name" ] && [ -f "$SAFE/$name" ]; then
    cp -p "$SAFE/$name" "$ROOT/$name" && restored=$((restored + 1))
    chmod 600 "$ROOT/$name" 2>/dev/null || true
    echo "♻️  بازگردانی شد: $name"
  fi
done

if [ -f "$ROOT/.env" ]; then
  chmod 600 "$ROOT/.env" 2>/dev/null || true
  current="$(sha256sum "$ROOT/.env" | cut -d' ' -f1)"
  if [ -f "$SAFE/.env.sha256" ]; then
    before="$(cut -d' ' -f1 < "$SAFE/.env.sha256")"
    if [ "$current" = "$before" ]; then
      echo "✅ .env دست‌نخورده و سالم است (هش یکسان)"
    else
      echo "⚠️ .env تغییر کرده است. اگر انتظارش را نداشتید، نسخه‌ی قبلی: $SAFE/.env"
    fi
  fi
else
  echo "⛔ هشدار: .env وجود ندارد و نسخه‌ی امنی هم پیدا نشد."
  echo "   ربات بدون سشن بالا نمی‌آید (کد خروج ۳). .env را از بکاپ برگردانید."
fi

if [ -f "$ROOT/.bot_instance" ]; then
  echo "ℹ️ نشانگر clone: $(tr -d ' \t\r\n' < "$ROOT/.bot_instance")"
fi

if [ -f "$ROOT/tools/secret_scan.py" ]; then
  echo "🔎 بررسی نشتی راز در فایل‌های مخزن:"
  python3 "$ROOT/tools/secret_scan.py" || echo "   (هشدار بالا را ببینید)"
fi

echo
echo "تمام. اگر pull انجام شد، ربات را دوباره اجرا کنید: ./b2.sh direct"
echo "پوشه‌ی امن را بعد از مطمئن‌شدن می‌توانید پاک کنید: rm -rf \"$SAFE\""
