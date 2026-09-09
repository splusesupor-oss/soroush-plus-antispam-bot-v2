"""💰 جایزهٔ بازی واقعاً روی حساب کاربر می‌نشیند.

باگ اصلی: توکن هر بازی از ``itertools.count(1)`` می‌آمد که با هر
ری‌استارت ربات دوباره از ۱ شروع می‌شد. چون ``reference`` جایزه از همان
توکن ساخته می‌شد، بعد از ری‌استارت مرجع‌ها تکرار می‌شدند، دفتر تراکنش
آن‌ها را «تکراری» می‌دید و پرداخت را رد می‌کرد — ولی پیام «+۳ سکه»
همچنان نمایش داده می‌شد و موجودی صفر می‌ماند.

سناریوی خواسته‌شدهٔ کاربر:
    ۱) موجودی قبل از بازی ثبت شود
    ۲) کاربر برنده شود
    ۳) سکه واقعاً ذخیره شود
    ۴) موجودی دوباره از دیتابیس خوانده شود و مقدار جدید را نشان دهد

    python tests/test_reward_persistence.py
"""
import asyncio
import itertools
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import economy
import economy.shop.store as store
import economy.storage as storage
import handlers.economy_handler as eco_handler
import modules.emoji_guess as emoji_guess
import modules.fill_blank as fill_blank
import modules.flag_guess as flag_guess
import modules.group_storage as group_storage
import modules.multiple_choice as multiple_choice
import modules.riddles as riddles
import modules.word_correction as word_correction
from economy import rewards
from test_economy_routing import build_handler, Event

PASSED = FAILED = 0
CHAT = -1009999888877


def check(label, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label} {detail}")


def fresh():
    temp = Path(tempfile.mkdtemp())
    storage.use_file(temp / "economy.json")
    store.ITEMS_FILE = temp / "shop.json"
    store._cache = None
    store._cache_mtime = None
    eco_handler.reset_all()
    flag_guess._ACTIVE.clear()
    flag_guess.reset_history()
    emoji_guess.reset_all()
    group_storage.activate_group(CHAT, "گروه تست")
    return temp


def simulate_restart(module=None):
    """ری‌استارت ربات: حافظه پاک، فایل دیتابیس دست‌نخورده."""
    if module is not None and hasattr(module, "_FALLBACK_TOKENS"):
        module._FALLBACK_TOKENS = itertools.count(1)
    storage._cache = None
    storage._cache_mtime = None
    # 🐛 fix: تاریخچه‌های ضدتکرار/ضداسپم هم in-memory هستند و با ری‌استارت
    # واقعی از بین می‌روند؛ بدون این پاکسازی، چهارمین «حدس پرچم» یکسان توسط
    # مسیر سریع تبلیغ/تکرار (رفتار درست ضداسپم) مجازات می‌شد و تست به‌غلط
    # fail می‌شد.
    from modules import spam_history, message_tracker
    spam_history.MESSAGE_HISTORY.clear()
    message_tracker._HISTORY.clear()


# ===========================================================================
# سناریوی چهار مرحله‌ای خواسته‌شده
# ===========================================================================
def test_four_step_scenario():
    print("\n### 💰 سناریوی چهار مرحله‌ای")
    fresh()

    async def scenario():
        bot, handler = await build_handler()
        # ۱) موجودی قبل از بازی
        before = economy.get_balance(CHAT, 900)[economy.BRONZE]
        # ۲) کاربر برنده می‌شود
        await handler(Event("حدس پرچم", 900))
        answer = flag_guess.get_active(CHAT)["answer"]
        event = Event(answer, 900)
        await handler(event)
        # ۴) موجودی دوباره از دیتابیس خوانده می‌شود
        storage._cache = None
        storage._cache_mtime = None
        after = economy.get_balance(CHAT, 900)[economy.BRONZE]
        return bot, before, after, event

    bot, before, after, event = asyncio.run(scenario())
    check("۱) موجودی اولیه صفر بود", before == 0, f"-> {before}")
    check("۲) پیام برد نمایش داده شد", event.said("پاسخ صحیح"))
    check("۳) دقیقاً ۳ برنز ذخیره شد", after - before == 3,
          f"{before} -> {after}")
    check("۴) موجودی جدید از دیتابیس خوانده می‌شود", after == 3,
          f"-> {after}")
    check("پیام موجودی جدید را نشان می‌دهد",
          event.said("𝟯"), f"-> {event.replies}")
    check("هیچ خطایی رخ نداد", not bot.logger.errors,
          f"-> {[e[:120] for e in bot.logger.errors][:1]}")


def test_balance_written_to_disk():
    print("\n### 💾 سکه واقعاً روی دیسک می‌نشیند")
    temp = fresh()

    async def scenario():
        bot, handler = await build_handler()
        await handler(Event("حدس پرچم", 901))
        answer = flag_guess.get_active(CHAT)["answer"]
        await handler(Event(answer, 901))

    asyncio.run(scenario())
    storage.flush()
    raw = json.loads((temp / "economy.json").read_text(encoding="utf-8"))
    key = economy.user_key(CHAT, 901)
    check("کاربر در فایل دیتابیس هست", key in raw["users"], f"-> {key}")
    check("مقدار برنز روی دیسک درست است",
          raw["users"][key]["bronze"] == 3,
          f"-> {raw['users'][key]['bronze']}")
    check("ارزش کل روی دیسک درست است",
          raw["users"][key]["total_coin_value"] == 3)


# ===========================================================================
# باگ اصلی: ری‌استارت
# ===========================================================================
def test_reward_survives_restart():
    """قلب باگ: بعد از ری‌استارت هم باید سکه اضافه شود."""
    print("\n### 🔄 جایزه پس از ری‌استارت هم پرداخت می‌شود")
    fresh()

    async def play(user_id):
        bot, handler = await build_handler()
        await handler(Event("حدس پرچم", user_id))
        state = flag_guess.get_active(CHAT)
        event = Event(state["answer"], user_id)
        await handler(event)
        return state["token"], event

    async def scenario():
        results = []
        token, event = await play(902)
        results.append((token, economy.get_balance(CHAT, 902)[economy.BRONZE],
                        event))
        for _ in range(3):
            flag_guess._ACTIVE.clear()
            flag_guess.reset_history()
            simulate_restart(flag_guess)
            token, event = await play(902)
            results.append(
                (token, economy.get_balance(CHAT, 902)[economy.BRONZE], event))
        return results

    results = asyncio.run(scenario())
    balances = [balance for _, balance, _ in results]
    tokens = [token for token, _, _ in results]

    check("موجودی هر بار ۳ تا زیاد می‌شود", balances == [3, 6, 9, 12],
          f"-> {balances}")
    check("توکن‌ها پس از ری‌استارت تکرار نمی‌شوند",
          len(set(tokens)) == len(tokens), f"-> {tokens}")
    check("آخرین پیام موجودی درست را نشان می‌دهد",
          results[-1][2].said("𝟭𝟮"), f"-> {results[-1][2].replies}")


def test_emoji_reward_survives_restart():
    print("\n### 🔄 حدس ایموجی پس از ری‌استارت")
    fresh()

    async def play(user_id):
        bot, handler = await build_handler()
        await handler(Event("حدس ایموجی", user_id))
        answer = emoji_guess.active_state(CHAT, user_id)["answer"]
        event = Event(answer, user_id)
        await handler(event)
        return event

    async def scenario():
        await play(903)
        first = economy.get_balance(CHAT, 903)[economy.BRONZE]
        emoji_guess.reset_all()
        simulate_restart(emoji_guess)
        event = await play(903)
        return first, economy.get_balance(CHAT, 903)[economy.BRONZE], event

    first, second, event = asyncio.run(scenario())
    check("بار اول ۴ برنز", first == 4, f"-> {first}")
    check("بعد از ری‌استارت هم ۴ برنز دیگر", second == 8, f"-> {second}")
    check("پیام موجودی تازه را نشان می‌دهد", event.said("𝟴"),
          f"-> {event.replies}")


def test_tokens_are_durable_for_every_game():
    print("\n### 🔄 توکن همهٔ بازی‌ها ماندگار است")
    fresh()
    modules = {
        "حدس پرچم": flag_guess,
        "حدس ایموجی": emoji_guess,
        "چیستان": riddles,
        "جای خالی": fill_blank,
        "تصحیح کلمات": word_correction,
        "چهار گزینه‌ای": multiple_choice,
    }
    for label, module in modules.items():
        check(f"«{label}» تابع توکن ماندگار دارد",
              hasattr(module, "_next_token"),
              "-> _next_token پیدا نشد")
        check(f"«{label}» شمارندهٔ حافظه‌ای را مستقیم استفاده نمی‌کند",
              hasattr(module, "_FALLBACK_TOKENS"))

    # توکن‌ها باید در کل سیستم یکتا باشند، نه فقط داخل یک بازی.
    produced = [module._next_token() for module in modules.values()]
    produced += [module._next_token() for module in modules.values()]
    check("توکن‌ها بین بازی‌ها هم یکتا هستند",
          len(set(produced)) == len(produced), f"-> {produced}")


def test_round_id_persists_across_restart():
    print("\n### 🔄 شمارندهٔ ماندگار روی دیسک می‌ماند")
    temp = fresh()
    first = [rewards.round_id() for _ in range(3)]
    storage.flush()
    simulate_restart()
    second = [rewards.round_id() for _ in range(3)]
    check("پس از ری‌استارت ادامه می‌دهد", min(second) > max(first),
          f"{first} -> {second}")
    check("هیچ تکراری نیست", not set(first) & set(second))


# ===========================================================================
# محافظ: پیام نباید جایزهٔ پرداخت‌نشده اعلام کند
# ===========================================================================
def test_no_false_reward_message():
    """اگر مرجع تکراری باشد، نباید «+۳ سکه» بگوید."""
    print("\n### 🛡 پیام دروغین جایزه داده نمی‌شود")
    fresh()

    async def scenario():
        bot, handler = await build_handler()
        # جایزه را با یک مرجع ثابت دو بار پرداخت می‌کنیم.
        economy.award_game(CHAT, 904, "flag", reference="fixed-ref")
        before = economy.get_balance(CHAT, 904)[economy.BRONZE]

        import handlers.message_handler as mh
        event = Event("x", 904)
        await mh._reward_game_reply(
            event, CHAT, 904, None, "flag", reference="fixed-ref")
        after = economy.get_balance(CHAT, 904)[economy.BRONZE]
        return before, after, event

    before, after, event = asyncio.run(scenario())
    check("موجودی تغییر نکرد", before == after == 3, f"{before} -> {after}")
    check("پیام «+۳ سکه دریافت کردید» نمی‌دهد",
          not event.said("دریافت کردید"), f"-> {event.replies}")
    check("توضیح می‌دهد قبلاً پرداخت شده",
          event.said("قبلاً"), f"-> {event.replies}")
    check("موجودی واقعی را نشان می‌دهد", event.said("𝟯"))


def test_message_shows_actual_gain():
    print("\n### 🛡 پیام مقدار واقعی اضافه‌شده را می‌گوید")
    fresh()

    async def scenario():
        import handlers.message_handler as mh
        event = Event("x", 905)
        await mh._reward_game_reply(
            event, CHAT, 905, None, "riddle", reference="r-unique")
        return event, economy.get_balance(CHAT, 905)

    event, balance = asyncio.run(scenario())
    check("چیستان ۳ برنز داد", balance[economy.BRONZE] == 3)
    check("پیام +۳ را اعلام کرد", event.said("𝟯"))
    check("موجودی نمایش‌داده‌شده با دیتابیس یکی است",
          event.said(f"🥉 𝟯"), f"-> {event.replies}")


# ===========================================================================
# همهٔ بازی‌ها به economy وصل‌اند
# ===========================================================================
def test_every_game_writes_to_economy():
    print("\n### 🔗 همهٔ بازی‌ها روی همان اقتصاد می‌نویسند")
    fresh()
    total_bronze = 0
    for game in ("riddle", "emoji", "flag", "correction", "quiz",
                 "fill_blank"):
        economy.award_game(CHAT, 906, game,
                           reference=f"{game}:{rewards.round_id()}")
        total_bronze += rewards.amount_for(game)

    storage._cache = None
    storage._cache_mtime = None
    balance = economy.get_balance(CHAT, 906)
    check("همهٔ برنزها در یک کیف پول جمع شدند",
          balance[economy.BRONZE] == total_bronze,
          f"-> {balance[economy.BRONZE]} != {total_bronze}")
    check("بردها شمرده شدند",
          economy.get_profile(CHAT, 906)["wins"] == 6)
    check("در پروفایل دیده می‌شود",
          economy.get_profile(CHAT, 906)[economy.BRONZE] == total_bronze)


def test_no_legacy_coin_system():
    print("\n### 🔗 هیچ بازی به سیستم قدیمی وصل نیست")
    import importlib
    for legacy in ("modules.coins", "modules.game_points"):
        try:
            importlib.import_module(legacy)
            check(f"{legacy} حذف شده", False)
        except ModuleNotFoundError:
            check(f"{legacy} حذف شده", True)

    handler_src = (ROOT / "handlers" / "message_handler.py").read_text(
        encoding="utf-8")
    check("هندلر از award_game استفاده می‌کند",
          "economy.award_game" in handler_src)
    check("هیچ فراخوانی مستقیم economy.award باقی نمانده",
          "economy.award(" not in handler_src)


def test_reward_visible_in_profile_and_balance():
    print("\n### 🔗 جایزه در پروفایل و موجودی دیده می‌شود")
    fresh()
    from economy import profiles
    from economy.ui import balance_menu, profile_menu

    async def scenario():
        bot, handler = await build_handler()
        await handler(Event("حدس پرچم", 907))
        answer = flag_guess.get_active(CHAT)["answer"]
        await handler(Event(answer, 907))

    asyncio.run(scenario())
    profiles.register(CHAT, 907, name="کیوان", city="شیراز", age=27)
    card, _ = profile_menu.render_card(CHAT, 907, None)
    check("برنز در کارت پروفایل", "🥉 برنز: ۳" in card, f"-> {card[:160]}")
    check("برد در کارت پروفایل", "🎮 برد: ۱" in card)
    menu, _ = balance_menu.render_menu(CHAT, 907)
    check("برنز در منوی موجودی", "🥉 برنز: ۳" in menu)
    check("ارزش کل در منوی موجودی", "💎 ارزش کل: ۳" in menu)


def test_repeated_wins_accumulate():
    print("\n### 🔗 بردهای پیاپی جمع می‌شوند")
    fresh()

    async def scenario():
        bot, handler = await build_handler()
        balances = []
        for _ in range(4):
            await handler(Event("حدس پرچم", 908))
            state = flag_guess.get_active(CHAT)
            if state is None:
                break
            await handler(Event(state["answer"], 908))
            balances.append(economy.get_balance(CHAT, 908)[economy.BRONZE])
        return balances

    balances = asyncio.run(scenario())
    check("هر برد ۳ تا اضافه می‌کند", balances == [3, 6, 9, 12],
          f"-> {balances}")


# ===========================================================================
def main():
    test_four_step_scenario()
    test_balance_written_to_disk()
    test_reward_survives_restart()
    test_emoji_reward_survives_restart()
    test_tokens_are_durable_for_every_game()
    test_round_id_persists_across_restart()
    test_no_false_reward_message()
    test_message_shows_actual_gain()
    test_every_game_writes_to_economy()
    test_no_legacy_coin_system()
    test_reward_visible_in_profile_and_balance()
    test_repeated_wins_accumulate()
    print(f"\npassed={PASSED} failed={FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
