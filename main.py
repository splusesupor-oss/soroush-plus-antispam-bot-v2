import os
import sys
import atexit

from core.bot_working_split_ok import SoroushAntiSpamBot
from modules.time_utils import TEHRAN, now_local
import asyncio


def _acquire_instance_lock():
    """Single-instance guard.

    دو پروس با همان session string نمی‌توانند همزمان کار کنند: سرور
    MTProto updateها را فقط به یکی می‌دهد و پروس دیگر زنده ولی
    بی‌تحرک می‌ماند (همه گروه‌ها «مرده» به نظر می‌رسند). این قفل از
    اجرای همزمان جلوگیری می‌کند و دلایلش را در ترمینال می‌نویسد.
    """
    try:
        from pathlib import Path
        from modules.runtime_paths import runtime_config_file
        lock = Path(runtime_config_file("bot.pid"))
    except Exception:
        return None
    pid = os.getpid()
    if lock.exists():
        try:
            old_pid = int((lock.read_text(encoding="utf-8").strip() or "0"))
        except Exception:
            old_pid = 0
        if 0 < old_pid and old_pid != pid:
            alive = False
            try:
                os.kill(old_pid, 0)
                alive = True
            except ProcessLookupError:
                alive = False
            except PermissionError:
                alive = False  # پروس دیگر متعلق به ما نیست؛ قفل را می‌گیریم
            if alive:
                print("=" * 62)
                print(" ⛔ BOT INSTANCE ALREADY RUNNING (pid=%d)" % old_pid)
                print("    با یک session string فقط یک پروس update می‌گیرد؛")
                print("    پروس دوم زنده است ولی هیچ پیامی نمی‌بیند.")
                print("    پروس فعلی (pid=%d) خارج می‌شود." % pid)
                print("    اول پروس قدیمی را ببند: kill %d" % old_pid)
                print("=" * 62)
                sys.exit(1)
    try:
        lock.write_text(str(pid), encoding="utf-8")
        atexit.register(
            lambda: _release_instance_lock(lock, pid))
    except Exception:
        pass
    return lock


def _release_instance_lock(lock, pid):
    try:
        if int((lock.read_text(encoding="utf-8").strip() or "0")) == pid:
            lock.unlink()
    except Exception:
        pass


async def main():
    _acquire_instance_lock()
    # نمایشِ زمانِ واقعیِ تهران در ترمینال هنگام راه‌اندازی، تا مشخص باشد
    # ربات واقعاً با چه زمانی کار می‌کند.
    _now = now_local()
    print(f"[START] Tehran time: {_now.strftime('%Y-%m-%d %H:%M:%S')} "
          f"({TEHRAN})")
    bot = SoroushAntiSpamBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
