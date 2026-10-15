"""🎯 بازطراحی چهار گزینه‌ای — بانک تازه، تصادفی بودن و تاریخچهٔ ماندگار.

    python tests/test_quiz_bank.py
"""
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ⚠️ پیش از import هر بازی: وگرنه economy مسیر config/economy.json
# واقعی را می‌بندد و تست روی دادهٔ زندهٔ کاربران می‌نویسد.
import tempfile as _tempfile
import economy.storage as _storage

_STORE_DIR = Path(_tempfile.mkdtemp())
_storage.use_file(_STORE_DIR / "economy.json")

import pytest


@pytest.fixture(autouse=True)
def _isolated_economy_store():
    """پشتیبان اقتصاد را پیش از هر تست به فایل اختصاصی همین ماژول برمی‌گرداند.

    انتخاب پشتیبان سراسری است و ماژول‌های دیگر سوییت هم عوضش می‌کنند
    (use_file/use_sqlite)؛ بدون این کار تست‌های فایل‌محورِ این فایل گاهی روی
    مسیر دیگری کار می‌کردند و با FileNotFoundError می‌شکستند.
    """
    _storage.use_file(_STORE_DIR / "economy.json")
    yield

import modules.multiple_choice as mc  # noqa: E402
from modules.quiz_questions import QUESTIONS  # noqa: E402

PASSED = FAILED = 0
CHAT = -880501
OTHER_CHAT = -880502


def check(label, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label} {detail}")


def draw(chat_id, user_id):
    """یک سوال می‌گیرد و بلافاصله می‌بندد (بدون پاسخ دادن)."""
    item = mc.start_question(chat_id, user_id)
    if item is not None:
        mc.clear_question(chat_id, item["token"])
    return item


# ===========================================================================
# ۱ و ۲ و ۳ — بانک تازه
# ===========================================================================
def test_old_questions_removed():
    print("\n### 🧹 حذف کامل سوال‌های قدیمی")
    texts = {q["question"] for q in QUESTIONS}
    # نمونه‌هایی از بانک قبلی که کاربر خواست حذف شوند.
    old = [
        "بنیان‌گذار شاهنشاهی هخامنشی چه کسی بود؟",
        "نماد شیمیایی عنصر اکسیژن چیست؟",
        "فرمول شیمیایی آب کدام است؟",
        "اگر ۳ سیب داشته باشید و ۲ سیب دیگر بگیرید، چند سیب دارید؟",
        "شاهنامه اثر کدام شاعر ایرانی است؟",
        "کدام شکل سه ضلع دارد؟",
    ]
    leftover = [q for q in old if q in texts]
    check("هیچ سوال قدیمی باقی نمانده", not leftover, f"-> {leftover}")

    categories = {q["category"] for q in QUESTIONS}
    removed_cats = {"دینی", "هوشی", "علمی", "تاریخی"} & categories
    check("دسته‌های قدیمی حذف شدند", not removed_cats, f"-> {removed_cats}")

    source = (ROOT / "modules" / "multiple_choice.py").read_text(
        encoding="utf-8")
    check("بانک از فایل منطق جدا شده است",
          "QUESTIONS = [" not in source)


def test_bank_size_and_levels():
    print("\n### 📚 اندازه و سطح دشواری")
    total = len(QUESTIONS)
    check("دست‌کم ۲۱۰ سوال دارد", total >= 210, f"-> {total}")
    check("total_questions هم‌خوان است", mc.total_questions() == total)

    levels = Counter(q.get("level") for q in QUESTIONS)
    check("فقط سطح متوسط و سخت وجود دارد",
          set(levels) == {"متوسط", "سخت"}, f"-> {dict(levels)}")
    check("هر دو سطح سهم معناداری دارند",
          min(levels.values()) >= total * 0.15, f"-> {dict(levels)}")


def test_topics_are_diverse():
    print("\n### 🗂 تنوع موضوعی")
    categories = Counter(q["category"] for q in QUESTIONS)
    check("دست‌کم ۲۰ موضوع مختلف", len(categories) >= 20,
          f"-> {len(categories)}")

    wanted = {
        "تاریخ", "جغرافیا", "فناوری", "کامپیوتر", "هوش مصنوعی", "اینترنت",
        "ورزش", "سینما", "موسیقی", "بازی‌های ویدیویی", "خودرو",
        "زبان انگلیسی", "ادبیات", "نجوم", "زیست‌شناسی", "شیمی", "فیزیک",
        "ریاضیات", "اطلاعات عمومی", "پرچم کشورها", "پایتخت کشورها",
        "مشاهیر جهان", "حیوانات", "طبیعت", "معماری", "اختراعات",
        "برندها", "ارزهای دیجیتال", "برنامه‌نویسی",
    }
    missing = wanted - set(categories)
    check("همهٔ موضوع‌های خواسته‌شده موجودند", not missing, f"-> {missing}")
    check("هیچ موضوعی بیش از ۱۵٪ بانک نیست",
          max(categories.values()) <= len(QUESTIONS) * 0.15,
          f"-> {categories.most_common(2)}")


def test_every_question_is_well_formed():
    print("\n### ✅ ساختار هر سوال")
    check("هر سوال دقیقاً ۴ گزینه دارد",
          all(len(q["options"]) == 4 for q in QUESTIONS),
          f"-> {[q['question'] for q in QUESTIONS if len(q['options']) != 4][:2]}")
    check("گزینه‌های هر سوال یکتا هستند",
          all(len(set(q["options"])) == 4 for q in QUESTIONS),
          f"-> {[q['question'] for q in QUESTIONS if len(set(q['options'])) != 4][:2]}")
    check("فقط یک پاسخ درست، بین ۱ تا ۴",
          all(1 <= q["answer"] <= 4 for q in QUESTIONS),
          f"-> {[q['question'] for q in QUESTIONS if not 1 <= q['answer'] <= 4][:2]}")
    check("هیچ گزینهٔ خالی نیست",
          all(str(o).strip() for q in QUESTIONS for o in q["options"]))
    check("هر سوال متن پرسش دارد",
          all(str(q["question"]).strip() for q in QUESTIONS))
    check("هر سوال دسته‌بندی دارد",
          all(str(q.get("category", "")).strip() for q in QUESTIONS))


def test_no_duplicate_or_near_duplicate():
    print("\n### 🔁 نبود سوال تکراری یا بسیار شبیه")
    texts = [q["question"] for q in QUESTIONS]
    dupes = [t for t, c in Counter(texts).items() if c > 1]
    check("هیچ متن پرسش تکراری نیست", not dupes, f"-> {dupes[:3]}")

    # «بسیار شبیه»: مجموعهٔ واژگان یکسان با ترتیب متفاوت.
    signatures = Counter(
        frozenset(t.replace("؟", "").split()) for t in texts
    )
    near = [s for s, c in signatures.items() if c > 1]
    check("هیچ دو سوالی واژگان یکسان ندارند", not near, f"-> {len(near)}")

    # یک سوال و پاسخ درستش نباید عیناً در سوال دیگری تکرار شود.
    pairs = Counter(
        (q["question"], q["options"][q["answer"] - 1]) for q in QUESTIONS)
    check("هیچ جفت پرسش/پاسخ تکراری نیست",
          all(c == 1 for c in pairs.values()))


def test_answer_position_is_spread():
    print("\n### 🎲 پخش بودن جایگاه پاسخ درست")
    positions = Counter(q["answer"] for q in QUESTIONS)
    check("هر چهار جایگاه استفاده شده‌اند",
          set(positions) == {1, 2, 3, 4}, f"-> {dict(positions)}")
    # اگر پاسخ همیشه گزینهٔ ۲ باشد، بازی با حدس زدن قابل بردن است.
    check("هیچ جایگاهی بیش از ۴۰٪ نیست",
          max(positions.values()) <= len(QUESTIONS) * 0.4,
          f"-> {dict(positions)}")


# ===========================================================================
# ۶ و ۷ — تصادفی بودن و نبود تکرار برای هر کاربر
# ===========================================================================
def test_no_repeat_for_one_user():
    print("\n### 🙋 بدون تکرار تا پایان بانک برای یک کاربر")
    mc.reset_all()
    total = len(QUESTIONS)
    seen = []
    for _ in range(total):
        item = draw(CHAT, 7001)
        seen.append(item["index"])
    check(f"همهٔ {total} سوال داده شد", len(seen) == total, f"-> {len(seen)}")
    check("هیچ سوالی تکرار نشد", len(set(seen)) == total,
          f"-> {len(set(seen))}")
    check("کل بانک پوشش داده شد", set(seen) == set(range(total)))
    check("کاربر اکنون exhausted است", mc.is_exhausted(CHAT, 7001))
    mc.reset_all()


def test_selection_is_random():
    print("\n### 🎲 انتخاب تصادفی است، نه ترتیبی")
    mc.reset_all()
    first = [draw(CHAT, 7002)["index"] for _ in range(30)]
    check("ترتیب با ۰،۱،۲،... یکسان نیست", first != list(range(30)))

    mc.reset_all()
    second = [draw(CHAT, 7002)["index"] for _ in range(30)]
    check("دو اجرای جداگانه ترتیب یکسان نمی‌دهند", first != second,
          f"-> {first[:5]} / {second[:5]}")
    mc.reset_all()


def test_different_users_get_different_questions():
    print("\n### 👥 کاربران مختلف سوال یکسان نمی‌گیرند")
    mc.reset_all()
    a = [draw(CHAT, 7003)["index"] for _ in range(25)]
    b = [draw(CHAT, 7004)["index"] for _ in range(25)]

    check("دنبالهٔ دو کاربر یکسان نیست", a != b)
    check("هر دو بدون تکرارند", len(set(a)) == 25 and len(set(b)) == 25)

    # مهم‌تر: سوال *اول* دو کاربر نباید یکی باشد، چون تاریخچهٔ اخیر گروه
    # سوال کاربر قبلی را کنار می‌گذارد.
    check("سوال اول دو کاربر متفاوت است", a[0] != b[0], f"-> {a[0]} / {b[0]}")
    check("همپوشانی کامل نیست", set(a) != set(b))
    mc.reset_all()


def test_second_user_not_blocked_by_first():
    print("\n### 👥 تاریخچهٔ کاربر اول کاربر دوم را محدود نمی‌کند")
    mc.reset_all()
    for _ in range(len(QUESTIONS)):
        draw(CHAT, 7005)
    check("کاربر اول همه را دیده", mc.is_exhausted(CHAT, 7005))
    check("کاربر دوم هنوز تاریخچه‌ای ندارد", mc.seen_count(CHAT, 7006) == 0)

    fresh = [draw(CHAT, 7006)["index"] for _ in range(40)]
    check("کاربر دوم ۴۰ سوال بدون تکرار گرفت", len(set(fresh)) == 40)
    mc.reset_all()


# ===========================================================================
# ۹ — تاریخچهٔ گروه: جلوگیری از تکرار پشت سر هم
# ===========================================================================
def test_group_prevents_back_to_back_repeat():
    print("\n### 👥 گروه از تکرار متوالی جلوگیری می‌کند")
    mc.reset_all()
    # هر بار کاربر تازه، پس تاریخچهٔ کاربری هیچ محدودیتی ایجاد نمی‌کند
    # و تنها عاملِ جلوگیری، تاریخچهٔ گروه است.
    picks = [draw(CHAT, 7100 + i)["index"] for i in range(mc.RECENT_WINDOW)]
    check("هیچ دو سوال متوالی یکسان نبود",
          all(picks[i] != picks[i + 1] for i in range(len(picks) - 1)))
    check("در پنجرهٔ اخیر گروه هیچ تکراری نبود",
          len(set(picks)) == len(picks), f"-> {len(set(picks))}/{len(picks)}")
    mc.reset_all()


def test_group_history_is_per_group():
    print("\n### 👥 تاریخچهٔ گروه‌ها از هم جداست")
    mc.reset_all()
    for i in range(10):
        draw(CHAT, 7200 + i)
    check("گروه اول تاریخچهٔ اخیر دارد",
          len(mc._progress.recent(CHAT, mc.GAME)) == 10)
    check("گروه دوم تاریخچهٔ اخیر ندارد",
          mc._progress.recent(OTHER_CHAT, mc.GAME) == [])

    check("کاربر در گروه دوم تاریخچهٔ مستقل دارد",
          mc.seen_count(OTHER_CHAT, 7200) == 0
          and mc.seen_count(CHAT, 7200) == 1)
    mc.reset_all()


def test_recent_window_is_bounded():
    print("\n### 📏 پنجرهٔ اخیر گروه محدود می‌ماند")
    mc.reset_all()
    for i in range(mc.RECENT_WINDOW + 25):
        draw(CHAT, 7300 + i)
    size = len(mc._progress.recent(CHAT, mc.GAME))
    check("اندازهٔ پنجره از سقف بیشتر نمی‌شود",
          size == mc.RECENT_WINDOW, f"-> {size}")
    mc.reset_all()


# ===========================================================================
# ۱۰ — بازگشت سوال‌های قدیمی به چرخه
# ===========================================================================
def test_oldest_questions_return_first():
    print("\n### ♻️ سوال‌های قدیمی‌تر زودتر به چرخه برمی‌گردند")
    mc.reset_all()
    user = 7400
    total = len(QUESTIONS)
    order = [draw(CHAT, user)["index"] for _ in range(total)]
    check("کاربر همهٔ بانک را دید", len(set(order)) == total)

    # پنجرهٔ اخیر گروه باید *پیش از* انتخاب خوانده شود؛ خود انتخاب
    # سوال تازه را به انتهای همین پنجره اضافه می‌کند و خواندن بعد از
    # آن، سوالِ همین لحظه را هم «اخیر» نشان می‌دهد.
    recent_before = {int(x) for x in mc._progress.recent(CHAT, mc.GAME)}

    # دور تازه: نباید None بدهد و نباید بازی بسته شود.
    nxt = mc.start_question(CHAT, user)
    check("بعد از اتمام، دور تازه شروع می‌شود", nxt is not None)
    if nxt is not None:
        mc.clear_question(CHAT, nxt["token"])
        check("شمارندهٔ دور یکی زیاد شد", mc.cycle(CHAT, user) == 1,
              f"-> {mc.cycle(CHAT, user)}")
        older = set(range(total)) - recent_before
        check("سوال دور تازه از میان قدیمی‌ترها انتخاب شد",
              nxt["index"] in older, f"-> {nxt['index']}")
        check("سوال دور تازه جزو تازه‌ترین‌های گروه نبود",
              nxt["index"] not in recent_before)
    mc.reset_all()


def test_game_never_locks_up():
    print("\n### 🔓 بازی هرگز قفل نمی‌شود")
    mc.reset_all()
    user = 7500
    # سه دور کامل پشت سر هم
    for _ in range(len(QUESTIONS) * 3):
        item = mc.start_question(CHAT, user)
        if item is None:
            break
        mc.clear_question(CHAT, item["token"])
    else:
        check("در سه دور کامل هرگز None نداد", True)
        mc.reset_all()
        return
    check("در سه دور کامل هرگز None نداد", False, "-> یک جا None داد")
    mc.reset_all()


# ===========================================================================
# ۱۱ — ماندگاری پس از ری‌استارت
# ===========================================================================
def test_history_survives_restart():
    print("\n### 💾 تاریخچه پس از ری‌استارت باقی می‌ماند")
    store = Path(tempfile.mkdtemp()) / "economy.json"

    script = f'''
import sys, pathlib
sys.path.insert(0, {str(ROOT)!r})
import economy.storage as st
st.use_file(pathlib.Path({str(store)!r}))
import modules.multiple_choice as mc
import json

phase = sys.argv[1]
CHAT, USER = -880777, 9001
if phase == "write":
    picked = []
    for _ in range(12):
        item = mc.start_question(CHAT, USER)
        mc.clear_question(CHAT, item["token"])
        picked.append(item["index"])
    st.flush()
    print(json.dumps({{"picked": picked,
                      "seen": mc.seen_count(CHAT, USER),
                      "recent": mc._progress.recent(CHAT, mc.GAME)}}))
else:
    nxt = []
    for _ in range(8):
        item = mc.start_question(CHAT, USER)
        mc.clear_question(CHAT, item["token"])
        nxt.append(item["index"])
    print(json.dumps({{"next": nxt,
                       "seen": mc.seen_count(CHAT, USER),
                       "recent": mc._progress.recent(CHAT, mc.GAME)}}))
'''
    path = Path(tempfile.mkdtemp()) / "restart_probe.py"
    path.write_text(script, encoding="utf-8")

    first = subprocess.run([sys.executable, str(path), "write"],
                           capture_output=True, text=True, timeout=180)
    check("پروسهٔ اول موفق بود", first.returncode == 0,
          f"-> {first.stderr[-300:]}")
    if first.returncode != 0:
        return
    before = json.loads(first.stdout.strip().splitlines()[-1])
    check("پروسهٔ اول ۱۲ سوال دید", before["seen"] == 12,
          f"-> {before['seen']}")

    # پروسهٔ کاملاً تازه = ری‌استارت واقعی ربات
    second = subprocess.run([sys.executable, str(path), "read"],
                            capture_output=True, text=True, timeout=180)
    check("پروسهٔ دوم موفق بود", second.returncode == 0,
          f"-> {second.stderr[-300:]}")
    if second.returncode != 0:
        return
    after = json.loads(second.stdout.strip().splitlines()[-1])

    check("تاریخچهٔ کاربر پاک نشد", after["seen"] == 20,
          f"-> {after['seen']}")
    overlap = set(before["picked"]) & set(after["next"])
    check("پس از ری‌استارت هیچ سوال تکراری داده نشد", not overlap,
          f"-> {overlap}")
    check("تاریخچهٔ اخیر گروه هم باقی ماند",
          len(after["recent"]) == 20, f"-> {len(after['recent'])}")


def test_progress_written_to_disk():
    print("\n### 💾 نوشته شدن واقعی روی دیسک")
    mc.reset_all()
    draw(CHAT, 7600)
    _storage.flush()
    raw = json.loads((_STORE_DIR / "economy.json").read_text(encoding="utf-8"))
    check("کلید پیشرفت در فایل هست", "game_progress" in raw)
    check("بازی چهار گزینه‌ای در فایل ثبت شده",
          any(mc.GAME in games
              for chat in raw.get("game_progress", {}).values()
              for games in chat.values()))
    check("تاریخچهٔ اخیر گروه در فایل ثبت شده",
          any(mc.GAME in chat
              for chat in raw.get("game_recent", {}).values()))
    mc.reset_all()


def test_index_stored_not_full_text():
    print("\n### ⚡ ساختار دادهٔ بهینه")
    mc.reset_all()
    draw(CHAT, 7700)
    stored = mc._progress.seen(CHAT, 7700, mc.GAME)
    check("فقط اندیس عددی ذخیره می‌شود، نه متن کامل",
          all(str(s).lstrip("-").isdigit() for s in stored), f"-> {stored}")
    mc.reset_all()


# ===========================================================================
# ۱۳ — قابلیت‌های قبلی نباید خراب شده باشند
# ===========================================================================
def test_answer_flow_still_works():
    print("\n### 🔄 پاسخ‌دهی مثل قبل کار می‌کند")
    mc.reset_all()
    item = mc.start_question(CHAT, 7800)
    correct = item["answer"]
    wrong = 1 if correct != 1 else 2

    check("پاسخ غلط False می‌دهد",
          mc.answer_question(CHAT, str(wrong), 7800) == (False, correct))
    check("بعد از پاسخ، سوال بسته شد",
          mc.get_active_question(CHAT) is None)

    item = mc.start_question(CHAT, 7800)
    check("پاسخ درست True می‌دهد",
          mc.answer_question(CHAT, str(item["answer"]), 7800)[0] is True)
    check("پاسخ دوباره اثری ندارد",
          mc.answer_question(CHAT, "1", 7800) is None)
    mc.reset_all()


def test_persian_digits_accepted():
    print("\n### 🔢 ارقام فارسی پذیرفته می‌شوند")
    mc.reset_all()
    item = mc.start_question(CHAT, 7900)
    persian = "۰۱۲۳۴۵۶۷۸۹"[item["answer"]]
    result = mc.answer_question(CHAT, persian, 7900)
    check("پاسخ با رقم فارسی درست خوانده شد", result == (True, item["answer"]),
          f"-> {result}")
    mc.reset_all()


def test_irrelevant_text_does_not_close_question():
    print("\n### 💬 متن نامرتبط سوال را نمی‌بندد")
    mc.reset_all()
    mc.start_question(CHAT, 8000)
    check("متن غیرعددی None می‌دهد",
          mc.answer_question(CHAT, "سلام", 8000) is None)
    check("عدد خارج از بازه None می‌دهد",
          mc.answer_question(CHAT, "9", 8000) is None)
    check("سوال هنوز فعال است", mc.get_active_question(CHAT) is not None)
    mc.reset_all()


def test_token_guards_timer():
    print("\n### ⏱ توکن تایمر قدیمی سوال تازه را نمی‌بندد")
    mc.reset_all()
    first = mc.start_question(CHAT, 8100)
    stale = first["token"]
    mc.clear_question(CHAT, stale)
    mc.start_question(CHAT, 8100)
    check("توکن قدیمی سوال جدید را نمی‌بندد",
          mc.clear_question(CHAT, stale) is False)
    check("سوال جدید هنوز فعال است",
          mc.get_active_question(CHAT) is not None)
    mc.reset_all()


def test_tokens_are_unique():
    print("\n### 🎫 توکن‌ها یکتا هستند")
    mc.reset_all()
    tokens = []
    for _ in range(20):
        item = mc.start_question(CHAT, 8200)
        tokens.append(item["token"])
        mc.clear_question(CHAT, item["token"])
    check("هیچ توکن تکراری نیست", len(set(tokens)) == len(tokens))
    mc.reset_all()


def test_public_api_intact():
    print("\n### 🔌 API عمومی دست‌نخورده است")
    for name in ("QUESTIONS", "ANSWER_SECONDS", "EXHAUSTED_MESSAGE",
                 "start_question", "answer_question", "get_active_question",
                 "clear_question", "is_exhausted", "total_questions",
                 "seen_count", "remaining_count", "reset_user", "reset_all"):
        check(f"«{name}» موجود است", hasattr(mc, name))
    check("ANSWER_SECONDS عدد مثبت است", mc.ANSWER_SECONDS > 0)
    check("EXHAUSTED_MESSAGE خالی نیست", bool(mc.EXHAUSTED_MESSAGE))
    check("QUESTIONS همان بانک تازه است", mc.QUESTIONS is QUESTIONS)


def test_handler_imports_still_resolve():
    print("\n### 🔗 هندلر همچنان می‌تواند import کند")
    source = (ROOT / "handlers" / "message_handler.py").read_text(
        encoding="utf-8")
    check("هندلر از multiple_choice import می‌کند",
          "from modules.multiple_choice import" in source)
    for name in ("start_question", "answer_question", "clear_question",
                 "get_active_question"):
        check(f"هندلر «{name}» را می‌بیند", hasattr(mc, name))


def test_no_storage_layer_leak():
    print("\n### 🧱 بازی مستقیم به لایهٔ storage دست نمی‌زند")
    source = (ROOT / "modules" / "multiple_choice.py").read_text(
        encoding="utf-8")
    check("economy.storage را import نمی‌کند",
          "economy.storage" not in source)
    check("storage.transaction صدا نمی‌زند",
          "storage.transaction" not in source)
    bank = (ROOT / "modules" / "quiz_questions.py").read_text(encoding="utf-8")
    check("فایل بانک هیچ import ی ندارد",
          "\nimport " not in bank and "\nfrom " not in bank)


# ===========================================================================
def main():
    test_old_questions_removed()
    test_bank_size_and_levels()
    test_topics_are_diverse()
    test_every_question_is_well_formed()
    test_no_duplicate_or_near_duplicate()
    test_answer_position_is_spread()

    test_no_repeat_for_one_user()
    test_selection_is_random()
    test_different_users_get_different_questions()
    test_second_user_not_blocked_by_first()

    test_group_prevents_back_to_back_repeat()
    test_group_history_is_per_group()
    test_recent_window_is_bounded()

    test_oldest_questions_return_first()
    test_game_never_locks_up()

    test_history_survives_restart()
    test_progress_written_to_disk()
    test_index_stored_not_full_text()

    test_answer_flow_still_works()
    test_persian_digits_accepted()
    test_irrelevant_text_does_not_close_question()
    test_token_guards_timer()
    test_tokens_are_unique()
    test_public_api_intact()
    test_handler_imports_still_resolve()
    test_no_storage_layer_leak()

    print(f"\npassed={PASSED} failed={FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
