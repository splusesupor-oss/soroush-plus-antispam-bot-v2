#!/usr/bin/env python3
"""Instance دوم ربات — فقط یک launcher است و هیچ کد رباتی duplicate نمی‌کند.

کار این فایل فقط این است که **قبل از import شدن هر ماژول پروجه** متغیر
``BOT_INSTANCE`` را روی ``bot2`` قرار دهد و بعد همان entrypoint واقعی
(main.py) را اجرا کند. همه‌ی مسیرهای runtime توسط
``modules/runtime_paths.py`` بر اساس همین instance جدا می‌شوند:

    python3 main.py  ->  ~/.local/share/soroush-bot/
    python3 bot2.py  ->  ~/.local/share/soroush-bot-bot2/

جدایی کامل runtime state هر instance:
    config/: groups.json, group_expiry.json, banned_users.json, bot.pid,
             state های bot_detector/group_level/punishment_mode/...
    logs/:   spam_counts.json, bot.log, error.log, backups/, archive/
    db/:     bot.sqlite3

قفل PID (bot.pid) به‌صورت per-instance است؛ main هرگز bot2 را مسدود
نمی‌کند و بالعکس.

Session: هر instance در زمان اجرای client، سلسله‌مراتب زیر را از محیط/
.env همان clone می‌خواند: SOROUSH_SESSION_STRING_<INSTANCE> و در نبودش
SOROUSH_SESSION_STRING. session فقط در حافظه است (StringSession) و هیچ
فایل session روی دیسک نوشته نمی‌شود؛ بنابراین session بین instanceها
انتقال یا لغزش پیدا نمی‌کند.
"""
import os

# MUST be قبل از import هر ماژول پروجه: modules/runtime_paths در زمان
# import، INSTANCE_NAME/DATA_DIR را از BOT_INSTANCE می‌سازد و .env هنوز
# لود نشده است. همین خط، instance را برای کل اجرای bot2.py قطعی می‌کند.
os.environ["BOT_INSTANCE"] = "bot2"

import asyncio

# import AFTER تعیین instance: بدنه‌ی main.py (تعیین dotenv و importهای
# پروجه) حالا با BOT_INSTANCE=bot2 اجرا می‌شود. بلاک if __name__ ==
# "__main__" در main.py هنگام import اجرا نمی‌شود.
import main

if __name__ == "__main__":
    asyncio.run(main.main())
