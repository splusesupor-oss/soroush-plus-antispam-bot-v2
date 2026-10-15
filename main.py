import os
import stat
import sys
import atexit

# --------------------------------------------------------------------------
# ترتیب اجرا در این فایل حیاتی است و نباید جابه‌جا شود:
#   1) تعیین قطعی instance (پیش از هر import پروژه)
#   2) لود .env بدون override
#   3) اعتبارسنجی instance با نشانگر clone  ← جلوگیری از نوشتن در داده ربات دیگر
#   4) ثبت مقادیر محرمانه برای ماسک‌کردن
#   5) import ماژول‌های سنگین پروژه
# --------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))

# launcher این clone — BOT_INSTANCE باید قبل از هر import پروژه
# (و قبل از لود شدن .env) قطعی شود: modules/runtime_paths در زمان
# import مقدارهای INSTANCE_NAME/DATA_DIR را از همین متغیر می‌سازد.
#
# نام instance از فایل نشانگر `.bot_instance` کنار همین فایل خوانده می‌شود تا
# اجرای مستقیم `python3 main.py` هرگز به runtime ربات دیگری برنگردد.
def _default_instance():
    marker = os.path.join(_HERE, ".bot_instance")
    try:
        with open(marker, "r", encoding="utf-8") as fh:
            name = fh.read().strip()
        if name:
            return name
    except OSError:
        pass
    return "main"


os.environ.setdefault("BOT_INSTANCE", _default_instance())

# .env باید قبل از هر import پروژه لود شود (override=False یعنی متغیرهای
# محیطی فعلی — از جمله BOT_INSTANCE بالا — بر .env برتری دارند).
from dotenv import load_dotenv
load_dotenv(override=False)

from modules import instance_guard  # noqa: E402  (بعد از تعیین instance)
from modules import secret_guard    # noqa: E402

# ۳) گارد جداسازی: تناقض بین محیط/لانچر/نشانگر = توقف روشن، نه ادامه‌ی خطرناک
try:
    _INSTANCE = instance_guard.resolve("main.py")
except instance_guard.InstanceConflict as _conflict:
    sys.stderr.write(str(_conflict) + "\n")
    sys.exit(2)

# ۴) رازها را ثبت کن تا در هیچ لاگ/خطا/گزارشی به‌صورت متن دیده نشوند
secret_guard.bootstrap(_HERE)


def _warn_if_env_is_world_readable():
    """سشن داخل .env است؛ مجوز فایل باید محدود باشد."""
    path = os.path.join(_HERE, ".env")
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        try:
            os.chmod(path, 0o600)
            print("[SECURITY] .env permissions were too open; fixed to 600")
        except OSError:
            print("[SECURITY] WARNING: .env is readable by other users "
                  "(chmod 600 recommended)")


_warn_if_env_is_world_readable()

from core.bot_working_split_ok import SoroushAntiSpamBot  # noqa: E402
from modules.time_utils import TEHRAN, now_local  # noqa: E402
import asyncio  # noqa: E402


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
        # 🐛 fix: migrate=False الزامی است — bot.pid یک فایل گذرا و
        # per-process است؛ کپی‌شدن bot.pid کهنهٔ instance اصلی (main) به
        # config یک instance تازه (bot2/bot3) باعث می‌شد instance جدید فکر
        # کند پروسه‌ی دیگری قفل را دارد و بی‌دلیل خارج شود.
        lock = Path(runtime_config_file("bot.pid", migrate=False))
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
                print("    instance=%s data_dir=%s" % (
                    _INSTANCE, os.path.dirname(str(lock))))
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
    try:
        from modules import runtime_paths
        _info = runtime_paths.describe()
        # سخت‌گیرانه: مسیر داده باید متعلق به همین instance باشد.
        instance_guard.assert_data_dir_is_own(_INSTANCE, _info["data_dir"])
        print(
            f"[INSTANCE] bot_instance={_info['instance']} "
            f"data_dir={_info['data_dir']} config_dir={_info['config_dir']} "
            f"log_dir={_info['log_dir']} db_dir={_info['db_dir']}"
        )
    except instance_guard.InstanceConflict as conflict:
        print(str(conflict))
        raise SystemExit(2)
    except Exception:
        pass
    # نمایشِ زمانِ واقعیِ تهران در ترمینال هنگام راه‌اندازی، تا مشخص باشد
    # ربات واقعاً با چه زمانی کار می‌کند.
    _now = now_local()
    print(f"[START] Tehran time: {_now.strftime('%Y-%m-%d %H:%M:%S')} "
          f"({TEHRAN})")
    bot = SoroushAntiSpamBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
