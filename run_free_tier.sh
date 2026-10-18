#!/usr/bin/env bash
# Dedicated free-tier runner. Keeps main.py and the existing launch scripts intact.
set -euo pipefail
cd "$(dirname "$0")"
export SOROUSH_BOT_PLAN=free
exec python3 watchdog.py --replace -- python3 -u free_tier.py
