#!/usr/bin/env python3
"""Instance دوم ربات — فقط یک launcher است و هیچ کد رباتی duplicate نمی‌کند.

کار این فایل فقط این است که **قبل از import شدن هر ماژول پروژه** متغیر
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

Session: هر instance سشن اختصاصی خودش را از ``SOROUSH_SESSION_STRING_BOT2``
می‌خواند. اگر این متغیر نباشد، سشن عمومی ``SOROUSH_SESSION_STRING`` فقط با
هشدار صریح و ماسک‌شده استفاده می‌شود (و با ``BOT_SESSION_STRICT=1`` کاملاً
غیرفعال است)، تا سشن ربات دیگری بی‌صدا قرض گرفته نشود.

⚠️ این clone باید نشانگر ``.bot_instance`` با مقدار ``bot2`` داشته باشد.
اگر نشانگر نباشد یا مقدار دیگری داشته باشد، ربات **بالا نمی‌آید** تا
اشتباهی داخل دایرکتوری داده‌ی ربات دیگری ننویسد.
"""
import os
import sys

# MUST be قبل از import هر ماژول پروژه: modules/runtime_paths در زمان
# import، INSTANCE_NAME/DATA_DIR را از BOT_INSTANCE می‌سازد و .env هنوز
# لود نشده است.
os.environ["BOT_INSTANCE"] = "bot2"

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from modules import instance_guard  # noqa: E402

try:
    # bootstrap=False: bot2.py هرگز نشانگر نمی‌سازد. اگر نشانگر نیست،
    # یعنی این clone واقعاً clone ربات ۲ نیست و باید اول با b2.sh مهر شود.
    instance_guard.resolve("bot2.py", instance="bot2")
except instance_guard.InstanceConflict as conflict:
    sys.stderr.write(str(conflict) + "\n")
    raise SystemExit(2)

import asyncio  # noqa: E402

from modules import secret_guard  # noqa: E402

secret_guard.bootstrap(_HERE)

# import AFTER تعیین instance: بدنه‌ی main.py (تعیین dotenv و importهای
# پروژه) حالا با BOT_INSTANCE=bot2 اجرا می‌شود. بلاک if __name__ ==
# "__main__" در main.py هنگام import اجرا نمی‌شود.
import main  # noqa: E402

if __name__ == "__main__":
    asyncio.run(main.main())
