"""تنظیمات مشترک تست‌های پروژه (فقط زمان تست — روی اجرای واقعی ربات اثری ندارد).

چرا این فایل لازم است
---------------------
هفت ماژول تست قدیمی در همان لحظهٔ import این خط را دارند::

    logging.disable(logging.CRITICAL)

``logging.disable`` روی **کل پروسه** اثر می‌گذارد، نه فقط همان فایل. پس هر
worker از pytest که یکی از آن هفت ماژول در آن import شود، برای بقیهٔ تست‌های
همان worker هم لاگ را خاموش می‌کند. نتیجه: تست‌هایی که باید رفتار لاگ را
بسنجند، بی‌صدا بی‌اعتبار می‌شدند (این موضوع در گزارش به‌عنوان مورد حل‌نشده
شمرده شده بود).

راه‌حل حداقلی: خودِ مسیر خاموش‌کردن دست‌نخورده می‌ماند (آن هفت فایل عمداً
می‌خواهند نویز لاگ‌شان را نبینند)، ولی قبل از اجرای نخستین تست، سطح لاگ به
حالت عادی برمی‌گردد و در پایان اجرا مقدار اولیه بازگردانده می‌شود.
"""
from __future__ import annotations

import logging

import pytest

# مقدار اولیه را همان‌جا که conftest قبل از collect شدن ماژول‌های تست import
# می‌شود ثبت می‌کنیم تا پایان اجرا دقیقاً همان بازگردانده شود.
_ORIGINAL_DISABLE = logging.root.manager.disable


@pytest.fixture(scope="session", autouse=True)
def _keep_logging_enabled_for_tests():
    """لاگ را برای طول اجرای تست‌ها فعال نگه می‌دارد.

    ``logging.disable(CRITICAL)`` در زمان collect (import ماژول‌ها) اجرا
    می‌شود؛ این fixture بلافاصله پس از collect و پیش از نخستین تست اجرا
    می‌شود و سطح را به ``NOTSET`` برمی‌گرداند.
    """
    logging.disable(logging.NOTSET)
    try:
        yield
    finally:
        logging.disable(_ORIGINAL_DISABLE)
