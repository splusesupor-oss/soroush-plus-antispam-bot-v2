"""Command Router بازی‌های Fox AI.

تنها نقطهٔ اتصال این چهار بازی به ربات. هیچ state ای اینجا نگه داشته
نمی‌شود؛ همه چیز داخل ماژول خودِ بازی است.

``handle`` مقدار True برمی‌گرداند یعنی پیام مصرف شد و هندلر اصلی نباید
ادامه دهد.
"""
from economy import award_game as economy_award_game
from economy import rewards as economy_rewards
from economy import spend as economy_spend
try:
    from splusthon.tl.types import MessageEntityBlockquote, MessageEntityBold
except ImportError:
    class MessageEntityBlockquote:
        def __init__(self, offset=0, length=0):
            self.offset = offset
            self.length = length
    class MessageEntityBold:
        def __init__(self, offset=0, length=0):
            self.offset = offset
            self.length = length
from modules.fox_games import (
    battle,
    best_answer,
    karagah,
    laugh_or_lose,
    lucky_box,
    maemma,
    minesweeper,
    sentence_guess,
    survival,
    vampire,
)
from modules.fox_games.session_core import (
    display_name,
    log,
    log_error,
    normalize_text,
    to_persian_digits,
)
# 🎮 گارد لایهٔ دوم: اگر این روتر روزی از مسیری غیر از هندلر اصلی صدا زده
# شود، بازیِ خاموش باز هم اجرا نمی‌شود. هیچ state یا تایمری پیش از این
# گارد ساخته نمی‌شود.
from modules import entertainment_control

# دستورهایی که این روتر مالک آن‌هاست.
FOX_GAME_COMMANDS = frozenset({
    "بخند یا بباز",
    "بقا",
    "جعبه شانسی",
    "خون آشام",
    "خون‌آشام",
    "معما",
    "حدس جمله",
    # همان بازی «حدس جمله» است، فقط با دستور دوم — بازی جدیدی ساخته نشده.
    "ساخت جمله",
    "مین یاب",
    "بهترین جواب",
    "نبرد",
    "کارگاه",
    "شرکت",
})


MAX_ACTIVE_GAMES_PER_CHAT = 2
LIMIT_EXCEEDED_MESSAGE = "در حال حاضر دو بازی فعال است، بعد از پایان آن‌ها دوباره تلاش کنید"


def any_active(chat_id):
    """آیا یکی از بازی‌های Fox در این چت فعال است."""
    return active_game_count(chat_id) > 0


def active_game_count(chat_id):
    """تعداد بازی‌های فعال Fox AI در یک چت به تفکیک گروه."""
    count = 0
    if laugh_or_lose.is_active(chat_id):
        count += 1
    if survival.is_active(chat_id):
        count += 1
    if lucky_box.is_active(chat_id):
        count += 1
    if vampire.is_active(chat_id):
        count += 1
    if best_answer.is_active(chat_id):
        count += 1
    if battle.is_active(chat_id):
        count += 1
    if maemma.is_active(chat_id):
        count += 1
    if sentence_guess.is_active(chat_id):
        count += 1
    if minesweeper.is_active(chat_id):
        count += 1
    if karagah.is_active(chat_id):
        count += 1
    return count


def _coins(bot, chat_id, user_id, name, amount, logger=None,
           reference=None, game="laugh_or_lose"):
    """جایزه را از راه API اقتصاد پرداخت می‌کند.

    نوع سکه از ``economy.rewards`` می‌آید: بقا و خون‌آشام «سخت»اند و نقره
    می‌دهند، بقیه برنز. مقدار همان مقدار قبلی هر بازی است.

    هیچ دسترسی مستقیمی به دیتابیس اقتصاد وجود ندارد. اگر تست متد
    ``award_coins`` را روی bot گذاشته باشد، همان ترجیح دارد.

    ``reference`` یکتا تضمین می‌کند یک جایزه دو بار پرداخت نشود.
    """
    override = getattr(bot, "award_coins", None)
    try:
        if override is not None:
            balance = override(chat_id, user_id, name, amount)
        else:
            balance = economy_award_game(
                chat_id, user_id, game, reference=reference, name=name,
                amount=amount,
            )
        log(logger, f"FOX REWARD PAID chat_id={chat_id} user_id={user_id} "
                    f"game={game} coin={economy_rewards.coin_for(game)} "
                    f"amount={amount} balance={balance}")
        return True
    except Exception as error:
        log_error(logger, f"FOX REWARD FAILED chat_id={chat_id} "
                          f"user_id={user_id} game={game} amount={amount} "
                          f"error={error!r}")
        return False


def coin_word(game):
    """نام سکهٔ این بازی، برای متن پیام برنده."""
    return economy_rewards.coin_name(economy_rewards.coin_for(game))


def _u16(text):
    """طول یک رشته به واحد UTF-16 (همان واحدی که MessageEntityها استفاده می‌کنند)."""
    return len(text.encode("utf-16-le")) // 2


async def _bold_reply(event, text, parts=()):
    """پیام را با بخش‌های مشخص‌شده Bold می‌فرستد.

    ``parts`` لیستی از زیررشته‌هایی است که باید Bold شوند؛ هر کجا در متن
    بیایند Bold می‌شوند. اگر سرور entityها را نپذیرد (که روی برخی نسخهٔ
    Soroush Plus رخ می‌دهد)، همان متن بدون قالب‌بندی فرستاده می‌شود تا
    کاربر هیچ‌وقت «خروجی خالی» نبیند.

    خروجی: شناسهٔ پیام ارسال‌شده (برای بازی‌هایی که به ریپلای نیاز دارند)
    یا None اگر نتوان مشخص کرد.
    """
    entities = []
    for part in parts:
        if not part:
            continue
        search = 0
        while True:
            pos = text.find(part, search)
            if pos == -1:
                break
            entities.append(MessageEntityBold(
                offset=_u16(text[:pos]),
                length=_u16(part),
            ))
            search = pos + len(part)
    sent = None
    try:
        sent = await event.reply(text, formatting_entities=entities or None)
    except Exception:
        try:
            sent = await event.reply(text)
        except Exception:
            pass
    if sent is None:
        return None
    return getattr(sent, "id", None)


async def _quote_reply(event, text, parts):
    """بخش‌های مشخص‌شده را هم Bold و هم داخل «نقل قول شیشه‌ای» (Blockquote) می‌کند.

    همان الگوی استفاده در اقتصاد/انقضا: span به دو entity تبدیل می‌شود تا
    متن هم پررنگ باشد هم در کادر نقل‌قول دیده شود. اگر سرور entityها را
    نپذیرد، متن بدون قالب‌بندی فرستاده می‌شود.
    """
    entities = []
    for part in parts:
        if not part:
            continue
        search = 0
        while True:
            pos = text.find(part, search)
            if pos == -1:
                break
            offset = _u16(text[:pos])
            length = _u16(part)
            entities.append(MessageEntityBold(offset=offset, length=length))
            entities.append(MessageEntityBlockquote(offset=offset, length=length))
            search = pos + len(part)
    try:
        await event.reply(text, formatting_entities=entities or None)
    except Exception:
        try:
            await event.reply(text)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 😂 بخند یا بباز
# ---------------------------------------------------------------------------
async def _start_laugh(bot, event, chat_id, logger):
    if laugh_or_lose.is_active(chat_id):
        await event.reply(laugh_or_lose.ALREADY_RUNNING)
        return True
    session = laugh_or_lose.start(chat_id, logger)
    if session is None:
        await event.reply(laugh_or_lose.ALREADY_RUNNING)
        return True

    await event.reply("😂 بخند یا بباز\n\nآماده باش...")

    async def on_countdown(remaining):
        await event.reply(f"{to_persian_digits(remaining)}...")

    async def on_open():
        await event.reply(
            "😂 حالا بخند!\n\n"
            "اولین نفری که یکی از این ایموجی‌ها را بفرستد برنده است:\n"
            "😂 🤣 😆 😹 😄 😁"
        )

    async def on_timeout():
        await event.reply(laugh_or_lose.NO_WINNER)

    laugh_or_lose.schedule(
        chat_id, session["session_id"],
        on_countdown, on_open, on_timeout, logger=logger,
    )
    return True


async def _laugh_message(bot, event, chat_id, user_id, sender, text, logger):
    if not laugh_or_lose.is_accepting(chat_id):
        return False
    if not laugh_or_lose.contains_laugh(text):
        return False
    win = laugh_or_lose.claim_win(chat_id, user_id, sender, logger)
    if win is None:
        return False
    paid = _coins(bot, chat_id, user_id, win["name"], win["coins"], logger,
                  reference=f"laugh:{chat_id}:{win['session_id']}",
                  game="laugh_or_lose")
    reward = (f"\n\n🪙 +{to_persian_digits(win['coins'])} سکه "
              f"{coin_word('laugh_or_lose')}" if paid else "")
    await event.reply(f"🏆 برنده: {win['name']}{reward}")
    return True


# ---------------------------------------------------------------------------
# 🏕 بقا
# ---------------------------------------------------------------------------
async def _start_survival(bot, event, chat_id, logger):
    if survival.is_active(chat_id):
        await event.reply(survival.ALREADY_RUNNING)
        return True
    session = survival.start(chat_id, logger)
    if session is None:
        await event.reply(survival.ALREADY_RUNNING)
        return True
    survival_session = session["session_id"]

    await event.reply(
        "🏕 بازی بقا\n\n"
        f"برای شرکت بنویسید: {survival.JOIN_WORD}\n\n"
        f"حداقل {to_persian_digits(survival.MIN_PLAYERS)} و حداکثر "
        f"{to_persian_digits(survival.MAX_PLAYERS)} نفر\n"
        f"⏳ مهلت ثبت‌نام: {to_persian_digits(survival.JOIN_SECONDS)} ثانیه"
    )

    async def on_abort():
        await event.reply(survival.NOT_ENOUGH)

    async def on_begin(names):
        lines = "\n".join(
            f"{to_persian_digits(i)}. {n}" for i, n in enumerate(names, 1)
        )
        await event.reply(f"🏕 بازی شروع شد!\n\n{lines}")

    async def on_question(question):
        await event.reply(
            f"🏕 مرحله {to_persian_digits(question['level'])}\n\n"
            f"{question['text']}\n\n"
            f"⏳ {to_persian_digits(survival.ANSWER_SECONDS)} ثانیه"
        )

    async def on_eliminated(names):
        await event.reply("❌ حذف شدند:\n" + "\n".join(f"• {n}" for n in names))

    async def on_finish(champion):
        if champion is None:
            # همه حذف شدند: هیچ سکه‌ای پرداخت نمی‌شود.
            await event.reply(survival.NO_WINNER)
            return
        paid = _coins(bot, chat_id, champion["user_id"], champion["name"],
                      survival.WINNER_COINS, logger,
                      reference=f"survival_win:{chat_id}:{survival_session}",
                      game="survival")
        rounds = champion.get("round_coins", 0)
        lines = [f"🏆 برندهٔ بقا: {champion['name']}"]
        if paid:
            lines.append("")
            if rounds:
                lines.append(
                    f"🪙 سکهٔ مراحل: +{to_persian_digits(rounds)}"
                )
            lines.append(
                f"🪙 جایزهٔ برنده: +{to_persian_digits(survival.WINNER_COINS)}"
            )
            lines.append(
                f"مجموع این بازی: "
                f"{to_persian_digits(rounds + survival.WINNER_COINS)} سکه"
            )
        await event.reply("\n".join(lines))

    survival.schedule(chat_id, session["session_id"], {
        "on_abort": on_abort,
        "on_begin": on_begin,
        "on_question": on_question,
        "on_eliminated": on_eliminated,
        "on_finish": on_finish,
    }, logger=logger)
    return True


async def _survival_message(bot, event, chat_id, user_id, sender, text, logger):
    if not survival.is_active(chat_id):
        return False
    state = survival.phase(chat_id)
    normalized = normalize_text(text)

    if state == "joining":
        if normalized != normalize_text(survival.JOIN_WORD):
            return False
        result, players = survival.join(chat_id, user_id, sender, logger)
        if result == "joined":
            confirmation = (
                f"✅ ثبت شد ({to_persian_digits(len(players))}"
                f"/{to_persian_digits(survival.MAX_PLAYERS)})"
            )
            # تا وقتی حداقل تعداد کامل نشده فقط پیام انتظار می‌آید؛ بازی
            # با اولین نفر شروع نمی‌شود.
            if not survival.has_minimum(chat_id):
                confirmation += "\n\n" + survival.waiting_message(chat_id)
            await event.reply(confirmation)
        elif result == "duplicate":
            await event.reply("⚠️ شما قبلاً ثبت‌نام کرده‌اید.")
        elif result == "full":
            await event.reply("⚠️ ظرفیت تکمیل است.")
        return True

    if state == "playing":
        # شناسهٔ session و شمارهٔ مرحله پیش از پردازش پاسخ برداشته می‌شوند
        # تا reference جایزه یکتا و پایدار بماند.
        active = survival._STORE.get(chat_id)
        state_id = active["session_id"] if active else 0
        level = active["level"] if active else 0
        result, player = survival.answer(chat_id, user_id, text, logger)
        if result in {"no_question", "not_player"}:
            return False
        if result == "already":
            return True
        if result == "correct":
            # سکهٔ مرحله بلافاصله پرداخت می‌شود؛ حذف شدن در مراحل بعد آن را
            # پس نمی‌گیرد.
            paid = _coins(bot, chat_id, user_id, player["name"],
                          survival.CORRECT_COINS, logger,
                          reference=f"survival_round:{chat_id}:"
                                    f"{state_id}:{level}:{user_id}",
                          game="survival_step")
            reward = (f" 🪙 +{to_persian_digits(survival.CORRECT_COINS)} سکه "
                      f"{coin_word('survival_step')}" if paid else "")
            await event.reply(f"✅ درست بود!{reward}")
        elif result == "wrong":
            await event.reply("❌ پاسخ اشتباه — حذف شدید.")
        return True
    return False


# ---------------------------------------------------------------------------
# 🎁 جعبه شانسی
# ---------------------------------------------------------------------------
async def _start_lucky_box(bot, event, chat_id, user_id, logger):
    session, error = lucky_box.start(chat_id, user_id, logger)
    if error == "active":
        await event.reply(lucky_box.ALREADY_RUNNING)
        return True
    if error == "quota":
        await event.reply(lucky_box.quota_message(user_id))
        return True

    await event.reply(
        "🎁 جعبه شانسی\n\n"
        f"{lucky_box.BOARD}\n\n"
        "شماره یک جعبه را بفرستید (۱ تا ۹)"
    )

    async def on_timeout():
        await event.reply("⏰ زمان انتخاب جعبه تمام شد.")

    lucky_box.schedule(chat_id, session["session_id"], on_timeout, logger=logger)
    return True


async def _lucky_box_message(bot, event, chat_id, user_id, sender, text, logger):
    if not lucky_box.is_active(chat_id):
        return False
    result, error = lucky_box.pick(chat_id, user_id, text, logger)
    if error in {"not_owner", None} and result is None:
        return False
    if error == "bad_number":
        return False
    if error == "done":
        return True
    if result is None:
        return False

    if result["prize"] > 0:
        paid = _coins(bot, chat_id, user_id, "", result["prize"], logger,
                      reference=f"luckybox:{chat_id}:{result['session_id']}",
                      game="lucky_box")
        reward = f"\n🪙 +{to_persian_digits(result['prize'])} سکه" if paid else ""
        await event.reply(
            f"🎁 جعبه {to_persian_digits(result['box'])} باز شد!\n\n"
            f"🎉 جایزه: {to_persian_digits(result['prize'])} سکه{reward}"
        )
    else:
        await event.reply(
            f"🎁 جعبه {to_persian_digits(result['box'])} باز شد!\n\n😔 پوچ بود."
        )
    return True


# ---------------------------------------------------------------------------
# 🧛 خون‌آشام
# ---------------------------------------------------------------------------
async def _start_vampire(bot, event, chat_id, logger):
    if vampire.is_active(chat_id):
        await event.reply(vampire.ALREADY_RUNNING)
        return True
    session = vampire.start(chat_id, logger)
    if session is None:
        await event.reply(vampire.ALREADY_RUNNING)
        return True

    await event.reply(
        "🧛 بازی خون‌آشام\n\n"
        f"برای شرکت بنویسید: {vampire.JOIN_WORD}\n\n"
        f"حداقل {to_persian_digits(vampire.MIN_PLAYERS)} و حداکثر "
        f"{to_persian_digits(vampire.MAX_PLAYERS)} نفر\n"
        f"⏳ مهلت ثبت‌نام: {to_persian_digits(vampire.JOIN_SECONDS)} ثانیه"
    )

    async def on_abort():
        await event.reply(vampire.NOT_ENOUGH)

    async def on_roles(chosen):
        """رساندن نقش — فقط پیام خصوصی، هرگز داخل گروه."""
        return await vampire.deliver_role(
            bot.client, chat_id, chosen, logger=logger,
        )

    async def on_roster(chosen):
        # اعلام عمومی: بدون هیچ اشاره‌ای به اینکه نقش برای چه کسی رفت.
        await event.reply(vampire.CHOSEN_MESSAGE)
        await event.reply(vampire.roster_lines(chosen["players"]))

    async def on_timeout(revealed):
        await event.reply(vampire.format_reveal(revealed))

    vampire.schedule(chat_id, session["session_id"], {
        "on_abort": on_abort,
        "on_roles": on_roles,
        "on_roster": on_roster,
        "on_timeout": on_timeout,
    }, logger=logger)
    return True


async def _vampire_message(bot, event, chat_id, user_id, sender, text, logger):
    if not vampire.is_active(chat_id):
        return False
    state = vampire.phase(chat_id)
    normalized = normalize_text(text)

    if state == "joining":
        if normalized != normalize_text(vampire.JOIN_WORD):
            return False
        result, players = vampire.join(chat_id, user_id, sender, logger)
        if result == "joined":
            await event.reply(
                f"✅ ثبت شد ({to_persian_digits(len(players))}"
                f"/{to_persian_digits(vampire.MAX_PLAYERS)})"
            )
        elif result == "duplicate":
            await event.reply("⚠️ شما قبلاً ثبت‌نام کرده‌اید.")
        elif result == "full":
            await event.reply("⚠️ ظرفیت تکمیل است.")
        return True

    if state == "guessing":
        active = vampire._STORE.get(chat_id)
        vampire_session = active["session_id"] if active else 0
        result, info = vampire.guess(chat_id, user_id, text, logger)
        if result in {"closed", "not_player", "bad_number"}:
            return False
        if result == "self_guess":
            await event.reply("⚠️ نمی‌توانید خودتان را انتخاب کنید.")
            return True
        if result in {"already", "is_vampire"}:
            return True
        if result == "wrong":
            await event.reply(f"❌ اشتباه بود، {info['guesser']['name']}!")
            return True
        if result == "correct":
            paid = _coins(bot, chat_id, user_id, info["guesser"]["name"],
                          info["coins"], logger,
                          reference=f"vampire:{chat_id}:{vampire_session}",
                          game="vampire")
            reward = (f"\n🪙 +{to_persian_digits(info['coins'])} سکه "
                      f"{coin_word('vampire')}" if paid else "")
            v_name = info["vampire"]["name"]
            v_tag = info["vampire"].get("tag") or ""
            tag = f" ({v_tag})" if v_tag and v_tag != v_name else ""
            await event.reply(
                f"🎯 درست حدس زدی، {info['guesser']['name']}!{reward}\n\n"
                f"🧛 خون‌آشام: {v_name}{tag}"
            )
            return True
    return False


# ---------------------------------------------------------------------------
# 🧩 حدس جمله / ساخت جمله — یک بازی، دو دستور
#
# «ساخت جمله» بازی تازه‌ای نیست: همان بازی حدس جمله است، فقط با نامِ دوم.
# نشست‌ها به‌تفکیکِ کاربر است، پس سوالِ هر کس مالِ خودش است و کسی جوابِ
# سوالِ دیگری را نمی‌بیند.
# ---------------------------------------------------------------------------
async def _start_sentence_guess(bot, event, chat_id, user_id, sender, logger, mode="guess"):
    import asyncio

    state = sentence_guess.start(chat_id, user_id, mode=mode)
    if state is None:
        await _bold_reply(
            event, "⏳ شما یک جملهٔ باز دارید؛ ابتدا همان را پاسخ دهید.")
        return True
    title = (f"🧩 {'ساخت جمله' if mode == 'build' else 'حدس بزن'} — سوال {to_persian_digits(state['number'])} "
             f"از {to_persian_digits(state['total'])}:")
    time_line = (f"⏳ {to_persian_digits(sentence_guess.TIMEOUT_SECONDS)} "
                 f"ثانیه فرصت دارید")
    question = state["question"]
    text = f"{title}\n\n{question}\n\n{time_line}"
    # Quote the complete clue with Soroush Plus Blockquote, not a literal >.
    entities = [
        MessageEntityBold(offset=0, length=_u16(title)),
        MessageEntityBlockquote(
            offset=_u16(text[:text.index(question)]),
            length=_u16(question),
        ),
    ]
    try:
        await event.reply(text, formatting_entities=entities)
    except Exception:
        await event.reply(text)

    async def on_timeout():
        await asyncio.sleep(sentence_guess.TIMEOUT_SECONDS)
        result = sentence_guess.timeout(chat_id, user_id, state["token"])
        if result:
            answer_text = result.get('answer', '') or ''
            text = f"⏰ زمان تمام شد!\n\n✅ پاسخ درست:\n{answer_text}"
            await _bold_reply(
                event,
                text, ["⏰ زمان تمام شد!", "✅ پاسخ درست:"])

    log(logger, f"SENTENCE GUESS START chat_id={chat_id} user_id={user_id} "
                f"number={state['number']}")
    # The timer starts only after the question has been sent.
    asyncio.create_task(on_timeout())
    return True


async def _sentence_guess_message(bot, event, chat_id, user_id, sender, text, logger):
    # فقط نشستِ خودِ همین کاربر بررسی می‌شود؛ پیامِ او روی بازی دیگران اثر ندارد.
    if not sentence_guess.has_active(chat_id, user_id):
        return False
    result = sentence_guess.answer(chat_id, text, user_id)
    if result is None:
        return True
    name = display_name(sender)
    paid = _coins(bot, chat_id, user_id, name, sentence_guess.REWARD, logger,
                  reference=f"sentence_guess:{chat_id}:{result['started_at']}:{user_id}",
                  game="sentence_guess")
    reward = (f"\n\n🪙 +{to_persian_digits(sentence_guess.REWARD)} سکه "
              f"{coin_word('sentence_guess')}") if paid else ""
    win_text = f"🎉 {name} پاسخ درست داد!"
    log(logger, f"SENTENCE GUESS CORRECT chat_id={chat_id} user_id={user_id} "
                f"answer={result['answer']!r} paid={paid}")
    await _bold_reply(event, f"{win_text}{reward}", [win_text])
    return True


# ---------------------------------------------------------------------------
# 💣 مین یاب
#
# تختهٔ ۳×۳، یک مینِ تصادفی در هر دور، بازیِ مستقل برای هر کاربر،
# ۲ شانس در روز با ریستِ ۰۰:۰۰ به وقتِ ایران.
# ---------------------------------------------------------------------------
def _minesweeper_penalty(bot, chat_id, user_id, reference, logger=None):
    """کسرِ سکه وقتی کاربر روی مین می‌رود. خروجی: کسر شد یا نه."""
    if minesweeper.PENALTY <= 0:
        return False
    try:
        economy_spend(chat_id, user_id, minesweeper.PENALTY,
                      economy_rewards.coin_for(minesweeper.REWARD_GAME),
                      reference=reference, note="مین یاب")
        log(logger, f"MINESWEEPER PENALTY chat_id={chat_id} "
                    f"user_id={user_id} amount={minesweeper.PENALTY}")
        return True
    except Exception as error:
        log_error(logger, f"MINESWEEPER PENALTY FAILED chat_id={chat_id} "
                          f"user_id={user_id} error={error!r}")
        return False


async def _start_minesweeper(bot, event, chat_id, user_id, sender, logger):
    session, error = minesweeper.start(chat_id, user_id, logger)
    if error == "active":
        await _bold_reply(event, minesweeper.ALREADY_RUNNING)
        return True
    if error == "quota":
        await _bold_reply(event, minesweeper.quota_message(user_id))
        return True

    title = "💣 مین یاب"
    hint = "یک خانه انتخاب کنید (۱ تا ۹)"
    remaining_line = (f"🎟 شانس باقی‌ماندهٔ امروز: "
                      f"{to_persian_digits(session['remaining'])} از "
                      f"{to_persian_digits(minesweeper.DAILY_CHANCES)}")
    text = (f"{title}\n\n{minesweeper.board_text()}\n\n"
            f"{hint}\n{remaining_line}")
    await _bold_reply(event, text, [title, hint])

    async def on_timeout(result):
        await _bold_reply(
            event,
            f"⏰ زمان تمام شد!\n\n{result['board']}\n\n"
            f"✅ خانهٔ امن در {to_persian_digits(result['mine'])} بود.",
            ["⏰ زمان تمام شد!"])

    minesweeper.schedule(chat_id, user_id, session["session_id"], on_timeout,
                         logger=logger)
    return True


async def _minesweeper_message(bot, event, chat_id, user_id, sender, text, logger):
    if not minesweeper.is_active(chat_id, user_id):
        return False
    result, error = minesweeper.pick(chat_id, user_id, text, logger)
    if error == "bad_number":
        return False
    if error == "done":
        return True
    if result is None:
        return False

    name = display_name(sender)
    reference = f"minesweeper:{chat_id}:{result['session_id']}:{user_id}"
    remaining_line = (f"🎟 شانس باقی‌ماندهٔ امروز: "
                      f"{to_persian_digits(result['remaining'])} از "
                      f"{to_persian_digits(minesweeper.DAILY_CHANCES)}")

    if result["safe"]:
        amount = economy_rewards.amount_for(minesweeper.REWARD_GAME)
        paid = _coins(bot, chat_id, user_id, name, amount, logger,
                      reference=reference, game=minesweeper.REWARD_GAME)
        headline = f"✅ {name} جان سالم به در برد!"
        reward = (f"\n🪙 +{to_persian_digits(amount)} سکه "
                  f"{coin_word(minesweeper.REWARD_GAME)}") if paid else ""
        await _bold_reply(
            event,
            f"{headline}\n\n{result['board']}\n\n"
            f"خانهٔ {to_persian_digits(result['cell'])} امن بود."
            f"{reward}\n{remaining_line}",
            [headline])
    else:
        # طبق طراحی مشخص‌شده: پیدا کردن مین → کسر ۱۰ سکه برنز
        headline = f"🧨 حدس اشتباه بود، مین منفجر شد!"
        paid_penalty = _minesweeper_penalty(
            bot, chat_id, user_id,
            reference=f"minesweeper:penalty:{chat_id}:{result['session_id']}:{user_id}",
            logger=logger)
        if paid_penalty:
            penalty_line = "\n🪙 ۱۰ سکه برنز از شما کم شد"
        else:
            penalty_line = "\n۱۰ سکه برنز نداری، بعد از جمع کردن سکه‌ها ازت کسر می‌شود."
        await _bold_reply(
            event,
            f"{headline}\n\n{result['board']}\n\n"
            f"💣 مین در خانهٔ {to_persian_digits(result['cell'])} بود."
            f"{penalty_line}\n{remaining_line}",
            [headline])
    return True


# ---------------------------------------------------------------------------
# 🧩 معما
# ---------------------------------------------------------------------------
async def _show_maemma_question(event, question, logger=None):
    """یک معما را نمایش می‌دهد (متن سوال Bold)."""
    title = f"🧩 معما — سوال {to_persian_digits(question['number'])} " \
            f"از {to_persian_digits(question['total'])}"
    time_line = f"⏳ {to_persian_digits(maemma.TIMEOUT_SECONDS)} ثانیه فرصت دارید"
    text = (
        f"{title}\n\n"
        f"{question['emoji']}\n\n"
        f"{time_line}"
    )
    await _bold_reply(event, text, [title, question['emoji'], time_line])


async def _start_maemma(bot, event, chat_id, user_id, sender, logger):
    if maemma.is_active(chat_id, user_id):
        await _bold_reply(event, "⏳ شما یک معما دارید؛ اول همان را پاسخ دهید.",
                          ["⏳ شما یک معما دارید؛ اول همان را پاسخ دهید."])
        return True
    state = maemma.start(chat_id, user_id, logger)
    if state is None:
        await _bold_reply(event, "⏳ امکان شروع معما نیست؛ کمی بعد دوباره تلاش کنید.",
                          ["⏳ امکان شروع معما نیست؛ کمی بعد دوباره تلاش کنید."])
        return True

    async def on_timeout(result):
        # فقط وقتی زمان تمام شود و کسی درست جواب نداده باشد، «پاسخ درست»
        # نمایش داده می‌شود؛ بعد از جوابِ درست این تایمر لغو می‌شود.
        t = "⏰ زمان تمام شد!"
        a = "✅ پاسخ درست:"
        text = f"{t}\n\n{a}\n{result['answer']}"
        await _bold_reply(event, text, [t, a, result["answer"]])

    first = maemma.current_question(chat_id, user_id)
    await _show_maemma_question(event, first, logger)
    maemma.schedule(
        chat_id, user_id, state["token"], on_timeout, logger=logger,
    )
    return True


async def _maemma_message(bot, event, chat_id, user_id, sender, text, logger):
    if not maemma.is_active(chat_id, user_id):
        return False
    result = maemma.answer(
        chat_id, user_id, display_name(sender), text, logger)
    if result is None:
        return False  # پاسخ اشتباه یا ناقص؛ مصرف نمی‌شود
    paid = _coins(bot, chat_id, user_id, result["name"], maemma.REWARD,
                  logger,
                  reference=f"maemma:{chat_id}:{user_id}:{result['token']}:"
                            f"{result['number']}",
                  game="maemma")
    # بعد از جوابِ درست فقط پیام موفقیت و جایزه نمایش داده می‌شود؛ هیچ
    # سوالِ بعدی یا پیامِ «زمان تمام شد» ارسال نمی‌شود.
    winner_name = display_name(sender)
    title = f"🎉 {winner_name} پاسخ درست داد!"
    reward = (f"\n\n🪙 +{to_persian_digits(maemma.REWARD)} سکه برنز"
              if paid else "")
    await _bold_reply(event, f"{title}{reward}", [title, reward.strip()])
    return True


# ---------------------------------------------------------------------------
# 🎯 بهترین جواب
# ---------------------------------------------------------------------------
async def _start_best_answer(bot, event, chat_id, logger):
    busy = "🎯 یک بازی «بهترین جواب» همین حالا در جریان است."
    if best_answer.is_active(chat_id):
        await _bold_reply(event, busy, [busy])
        return True
    session = best_answer.start(chat_id, logger)
    if session is None:
        await _bold_reply(event, busy, [busy])
        return True
    title = "🎯 بهترین جواب"
    prompt = "برای ثبت پاسخ، روی سوال ریپلای کنید و جواب خود را ارسال کنید."
    time_line = f"⏳ {to_persian_digits(best_answer.ANSWER_SECONDS)} ثانیه"
    text = (
        f"{title}\n\n"
        f"{session['question']}\n\n"
        f"{prompt}\n\n"
        f"{time_line}"
    )
    question_msg_id = await _bold_reply(
        event, text, [title, session['question'], prompt, time_line])
    # شناسهٔ پیامِ سوال را نگه می‌داریم تا فقط ریپلایِ مستقیمِ به آن ثبت شود.
    best_answer.set_question_msg_id(chat_id, question_msg_id)

    async def on_finish(winner):
        if winner is None:
            msg = "🎯 هیچ پاسخ درستی ثبت نشد."
            await _bold_reply(event, msg, [msg])
            return
        paid = _coins(
            bot, chat_id, winner["user_id"], winner["name"],
            best_answer.REWARD, logger,
            reference=f"best_answer:{chat_id}:{winner['session_id']}",
            game="best_answer",
        )
        head = f"🏆 بهترین پاسخ: {winner['name']}"
        quote = f"«{winner['text']}»"
        reward = (f"\n\n🪙 +{to_persian_digits(best_answer.REWARD)} سکه برنز"
                  if paid else "")
        text = f"{head}\n\n{quote}{reward}"
        await _bold_reply(event, text, [head, quote, reward.strip()])

    best_answer.schedule(
        chat_id, session["session_id"], on_finish, logger=logger,
    )
    return True


async def _best_answer_message(bot, event, chat_id, user_id, sender, text, logger):
    if not best_answer.is_active(chat_id):
        return False
    # شناسهٔ پیامی که این پیام به آن ریپلای شده است (اگر ریپلای باشد).
    reply_to = getattr(event, "reply_to", None)
    reply_to_msg_id = getattr(reply_to, "reply_to_msg_id", None)
    result = best_answer.submit(
        chat_id, user_id, display_name(sender), text,
        reply_to_msg_id=reply_to_msg_id, logger=logger)
    if result is None:
        return False
    if result == "not_reply":
        # پیامِ عادی بدون ریپلایِ به سوال؛ ثبت نمی‌شود و مصرف هم نمی‌شود
        return False
    if result == "already":
        return True  # پاسخ قبلاً ثبت شده؛ ساکت
    msg = "✅ پاسخ شما ثبت شد!"
    await _bold_reply(event, msg, [msg])
    return True


# ---------------------------------------------------------------------------
# ⚔️ نبرد
# ---------------------------------------------------------------------------
async def _start_battle(bot, event, chat_id, user_id, sender, logger):
    if battle.is_active(chat_id):
        await _bold_reply(event, battle.ALREADY_RUNNING, [battle.ALREADY_RUNNING])
        return True
    session = battle.start(chat_id, user_id, display_name(sender), logger)
    if session is None:
        await _bold_reply(event, battle.ALREADY_RUNNING, [battle.ALREADY_RUNNING])
        return True
    title = "⚔️ نبرد شروع شد!"
    you = "شما بازیکن اول هستید."
    join_prompt = "برای پیوستن بازیکن دوم بنویسید:"
    join_word = "شرکت"
    time_line = f"⏳ مهلت ثبت‌نام: {to_persian_digits(battle.JOIN_SECONDS)} ثانیه"
    text = (
        f"{title}\n\n"
        f"{you}\n"
        f"{join_prompt}\n"
        f"{join_word}\n\n"
        f"{time_line}"
    )
    await _bold_reply(event, text, [title, you, join_prompt, join_word, time_line])

    async def on_abort():
        await _bold_reply(event, battle.NOT_ENOUGH, [battle.NOT_ENOUGH])

    battle.schedule_join_timeout(
        chat_id, session["session_id"], on_abort, logger=logger,
    )
    return True


async def _battle_message(bot, event, chat_id, user_id, sender, text, logger):
    if not battle.is_active(chat_id):
        return False
    state = battle.phase(chat_id)

    if state == "joining":
        if normalize_text(text) != normalize_text(battle.JOIN_WORD):
            return False
        result, players = battle.join(
            chat_id, user_id, display_name(sender), logger)
        if result == "duplicate":
            msg = "⚠️ شما بازیکن اول هستید؛ نمی‌توانید دوباره وارد شوید."
            await _bold_reply(event, msg, [msg])
            return True
        if result == "full":
            msg = "⚠️ نبرد همین حالا پر است."
            await _bold_reply(event, msg, [msg])
            return True
        if result == "not_open":
            return False
        joined = "⚔️ بازیکن دوم پیوست! نبرد شروع می‌شود..."
        await _bold_reply(event, joined, [joined])
        session = battle.begin(chat_id, logger)
        if session is None:
            return True
        p1, p2 = session["p1"], session["p2"]

        async def on_question(player_num, qnum, q, assignee):
            title = f"⚔️ بازیکن {to_persian_digits(player_num)} — سوال {to_persian_digits(qnum)}"
            time_line = f"⏳ {to_persian_digits(battle.ANSWER_SECONDS)} ثانیه"
            for_line = f"برای: {p1['name'] if assignee == p1['user_id'] else p2['name']}"
            text = (
                f"{title}\n\n"
                f"{q['question']}\n\n"
                f"{time_line}\n"
                f"{for_line}"
            )
            await _bold_reply(event, text,
                              [title, q['question'], time_line, for_line])

        async def on_answer(result, assignee, player_num, qnum):
            if result == "correct":
                msg = "✅ پاسخ درست بود!"
            elif result == "wrong":
                msg = "❌ پاسخ اشتباه بود!"
            else:
                # بدون پاسخ در مهلت → بدون امتیاز، اما بازی ادامه می‌یابد
                msg = "⏰ زمان تمام شد!"
            await _bold_reply(event, msg, [msg])

        async def on_finish(result):
            header = "🏁 پایان نبرد!"
            score1 = f"{result['p1']['name']}: {to_persian_digits(result['score1'])}"
            score2 = f"{result['p2']['name']}: {to_persian_digits(result['score2'])}"
            if result["tie"]:
                outcome = "🤝 مساوی شد."
            else:
                w_name = (result["p1"]["name"]
                          if result["winner"] == result["p1"]["user_id"]
                          else result["p2"]["name"])
                outcome = f"🏆 برنده: {w_name}"

            # جایزه: ۲ سکه برنز به برنده؛ اگر مساوی (غیر از ۰-۰) به هر دو بازیکن ۲ سکه.
            # نکته: مساویِ صفر-صفر امتیازی ندارد (هیچ‌کس جوابِ درست نداده).
            s1 = result.get("score1", 0)
            s2 = result.get("score2", 0)
            reward_lines = []
            if result["tie"]:
                if s1 > 0 or s2 > 0:
                    # مساوی با امتیازِ غیرصفر (۱-۱، ۲-۲، ...) → هر دو جایزه می‌گیرند
                    for p in (result["p1"], result["p2"]):
                        paid = _coins(
                            bot, chat_id, p["user_id"], p["name"], battle.REWARD,
                            logger,
                            reference=f"battle:{chat_id}:{result['session_id']}:"
                                      f"{p['user_id']}",
                            game="battle",
                        )
                        if paid:
                            reward_lines.append(
                                f"🪙 {p['name']} +{to_persian_digits(battle.REWARD)} سکه برنز"
                            )
                # اگر مساویِ صفر-صفر بود → هیچ جایزه‌ای
            elif result["winner"] is not None:
                w = (result["p1"] if result["winner"] == result["p1"]["user_id"]
                     else result["p2"])
                paid = _coins(
                    bot, chat_id, w["user_id"], w["name"], battle.REWARD, logger,
                    reference=f"battle:{chat_id}:{result['session_id']}:winner",
                    game="battle",
                )
                if paid:
                    reward_lines.append(
                        f"🪙 {w['name']} +{to_persian_digits(battle.REWARD)} سکه برنز"
                    )

            reward_text = ("\n" + "\n".join(reward_lines)) if reward_lines else ""
            text = (
                f"{header}\n\n"
                f"{score1}\n"
                f"{score2}\n\n"
                f"{outcome}{reward_text}"
            )
            # نام و امتیاز هر بازیکن داخل «نقل قول شیشه‌ای» (Blockquote)
            await _quote_reply(event, text, [score1, score2])

        battle.schedule_game(chat_id, on_question, on_answer, on_finish, logger=logger)
        return True

    if state == "playing":
        # تلاش یک نفر سوم برای پیوستن به نبردِ در جریان → رد و هشدار
        if normalize_text(text) == normalize_text(battle.JOIN_WORD):
            p1 = battle.players(chat_id)
            uids = {p["user_id"] for p in p1 if p}
            if user_id not in uids:
                msg = "⚠️ نبرد همین حالا در جریان است؛ نمی‌توانید وارد شوید."
                await _bold_reply(event, msg, [msg])
                return True
        result, _info = battle.answer(chat_id, user_id, text, logger)
        # هنگام بازی، هیچ پیامِ پاداشی/خطایی نمایش داده نمی‌شود تا خروجی
        # تمیز بماند؛ فقط سوال‌ها و در پایان، نتیجهٔ نهایی و جایزه اعلام می‌شود.
        if result in {"no_game", "no_question"}:
            return False
        if result in {"not_assignee", "already", "correct", "wrong"}:
            return True
    return False


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 🕵️ کارگاه — پیدا کردن دزد و شیء دزدیده‌شده (همان چرخهٔ اثبات‌شدهٔ خون‌آشام)
# ---------------------------------------------------------------------------
async def _start_karagah(bot, event, chat_id, logger):
    if karagah.is_active(chat_id):
        await event.reply(karagah.ALREADY_RUNNING)
        return True
    session = karagah.start(chat_id, logger)
    if session is None:
        await event.reply(karagah.ALREADY_RUNNING)
        return True

    await event.reply(
        "🕵️ پرونده جدید ساخته شد\n\n"
        "منتظر بازیکنان...\n\n"
        f"تعداد مورد نیاز: {to_persian_digits(karagah.MIN_PLAYERS)} تا "
        f"{to_persian_digits(karagah.MAX_PLAYERS)} نفر\n\n"
        f"برای شرکت بنویسید: {karagah.JOIN_WORD}\n"
        f"⏳ مهلت ثبت‌نام: {to_persian_digits(karagah.JOIN_SECONDS)} ثانیه"
    )

    async def on_abort():
        await event.reply(karagah.NOT_ENOUGH)

    async def on_dm_failed():
        await event.reply(karagah.DM_FAILED_MESSAGE)

    async def on_roles(chosen):
        # نقش دزد فقط از راه پیوی؛ هرگز داخل گروه.
        return await karagah.deliver_role(bot.client, chat_id, chosen, logger=logger)

    async def on_roster(chosen):
        await event.reply(
            "🕵️ پرونده جدید ساخته شد\n\n"
            "شرکت‌کنندگان:\n\n"
            f"{karagah.roster_lines(chosen['players'])}\n\n"
            "دزد انتخاب شد و به پیوی شخصی یک نفر ارسال شد 🤫\n\n"
            "شروع پرونده؟\n"
            "🕵️ دزد را با «شماره» حدس بزنید\n"
            f"⏳ {to_persian_digits(karagah.THIEF_GUESS_SECONDS)} ثانیه فرصت دارید"
        )

    async def on_thief_win(result):
        thief = result.get("thief") or {}
        paid = _coins(bot, chat_id, thief.get("user_id"), thief.get("name", "دزد"),
                      karagah.THIEF_BRONZE, logger,
                      reference=f"karagah:{chat_id}:{session['session_id']}:thief",
                      game="karagah_thief")
        reward = (f"\n🥉 +{to_persian_digits(karagah.THIEF_BRONZE)} سکه برنز برای دزد"
                  if paid else "")
        stolen = result.get("object") or "—"
        await event.reply(
            "⏰ زمان تمام شد!\n\n"
            "😈 دزد برنده شد!\n\n"
            f"🕵️ دزد: {thief.get('name', '—')}\n"
            f"🎒 شیء دزدیده‌شده: {stolen}{reward}"
        )

    karagah.schedule(chat_id, session["session_id"], {
        "on_abort": on_abort,
        "on_dm_failed": on_dm_failed,
        "on_roles": on_roles,
        "on_roster": on_roster,
        "on_thief_win": on_thief_win,
    }, logger=logger)
    return True


async def _karagah_message(bot, event, chat_id, user_id, sender, text, logger):
    if not karagah.is_active(chat_id):
        return False
    state = karagah.phase(chat_id)
    normalized = normalize_text(text)
    session = karagah._STORE.get(chat_id)
    session_id = session["session_id"] if session else 0

    if state == "joining":
        if normalized != normalize_text(karagah.JOIN_WORD):
            return False
        result, players = karagah.join(chat_id, user_id, sender, logger)
        if result == "joined":
            await event.reply(
                f"✅ ثبت شد ({to_persian_digits(len(players))}"
                f"/{to_persian_digits(karagah.MAX_PLAYERS)})"
            )
        elif result == "duplicate":
            await event.reply("⚠️ شما قبلاً ثبت‌نام کرده‌اید.")
        elif result == "full":
            await event.reply("⚠️ ظرفیت تکمیل است.")
        return True

    if state == "thief_guess":
        result, info = karagah.guess_thief(chat_id, user_id, text, logger)
        if result in {"closed", "not_player", "bad_number"}:
            return False
        if result == "self_guess":
            await event.reply("⚠️ نمی‌توانید خودتان را انتخاب کنید.")
            return True
        if result in {"already", "is_thief"}:
            return True
        if result == "wrong":
            await event.reply(f"❌ اشتباه بود، {info['guesser']['name']}!")
            return True
        if result == "found":
            options_text = "\n".join(
                f"{index}) {option}"
                for index, option in enumerate(info["options"], 1)
            )
            await event.reply(
                f"🎯 آفرین {info['guesser']['name']}! دزد را پیدا کردی!\n\n"
                f"🕵️ دزد: {info['thief']['name']}\n\n"
                "حالا حدس بزن چه چیزی دزدیده شده؟\n\n"
                f"{options_text}\n\n"
                "شماره گزینه را بفرست\n"
                f"⏳ {to_persian_digits(karagah.OBJECT_GUESS_SECONDS)} ثانیه فرصت داری"
            )
            return True
        return False

    if state == "object_guess":
        result, info = karagah.guess_object(chat_id, user_id, text, logger)
        if result in {"closed", "not_finder", "bad_option"}:
            return False
        if result == "solved":
            paid = _coins(bot, chat_id, user_id, info["finder"]["name"],
                          karagah.WINNER_SILVER, logger,
                          reference=f"karagah:{chat_id}:{session_id}:winner",
                          game="karagah")
            reward = (f"\n🥈 +{to_persian_digits(karagah.WINNER_SILVER)} سکه نقره"
                      if paid else "")
            await event.reply(
                "🏆 پرونده حل شد!\n\n"
                f"✅ شیء دزدیده‌شده: {info['object']}\n"
                f"🎉 برنده: {info['finder']['name']}{reward}"
            )
            return True
        if result == "object_wrong":
            paid = _coins(bot, chat_id, info["thief"]["user_id"],
                          info["thief"]["name"], karagah.THIEF_BRONZE, logger,
                          reference=f"karagah:{chat_id}:{session_id}:thief",
                          game="karagah_thief")
            reward = (f"\n🥉 +{to_persian_digits(karagah.THIEF_BRONZE)} سکه برنز برای دزد"
                      if paid else "")
            await event.reply(
                "❌ حدس شیء اشتباه بود!\n\n"
                "😈 دزد برنده شد!\n\n"
                f"🎒 شیء دزدیده‌شده: {info['object']}\n"
                f"🕵️ دزد: {info['thief']['name']}{reward}"
            )
            return True
    return False


async def handle(bot, event, chat_id, user_id, sender, text, logger=None):
    """پیام را به بازی مربوطه می‌سپارد. True یعنی پیام مصرف شد."""
    command = normalize_text(text)

    start_games = {
        normalize_text("بخند یا بباز"): (laugh_or_lose, _start_laugh),
        normalize_text("بقا"): (survival, _start_survival),
        normalize_text("جعبه شانسی"): (lucky_box, lambda b, e, c, l: _start_lucky_box(b, e, c, user_id, l)),
        normalize_text("خون آشام"): (vampire, _start_vampire),
        normalize_text("خون‌آشام"): (vampire, _start_vampire),
        normalize_text("معما"): (maemma, lambda b, e, c, l: _start_maemma(b, e, c, user_id, sender, l)),
        normalize_text("حدس جمله"): (sentence_guess, lambda b, e, c, l: _start_sentence_guess(b, e, c, user_id, sender, l, mode="guess")),
        normalize_text("ساخت جمله"): (sentence_guess, lambda b, e, c, l: _start_sentence_guess(b, e, c, user_id, sender, l, mode="build")),
        normalize_text("مین یاب"): (minesweeper, lambda b, e, c, l: _start_minesweeper(b, e, c, user_id, sender, l)),
        normalize_text("بهترین جواب"): (best_answer, _start_best_answer),
        normalize_text("نبرد"): (battle, lambda b, e, c, l: _start_battle(b, e, c, user_id, sender, l)),
        normalize_text("کارگاه"): (karagah, _start_karagah),
    }

    if command in start_games:
        # 🎮 لایهٔ دوم گارد سرگرمی — پیش از هر state، تایمر یا پرداخت سکه.
        if await entertainment_control.guard(event, chat_id, text):
            log(logger, f"FOX GAME BLOCKED chat_id={chat_id} command={command!r}")
            return True
        game_module, starter = start_games[command]
        if not game_module.is_active(chat_id):
            if active_game_count(chat_id) >= MAX_ACTIVE_GAMES_PER_CHAT:
                await event.reply(LIMIT_EXCEEDED_MESSAGE)
                return True
        return await starter(bot, event, chat_id, logger)

    # پیام‌های درون‌بازی — هر بازی فقط session خودش را می‌بینند.
    for responder in (
        _laugh_message, _survival_message, _lucky_box_message, _vampire_message,
        _maemma_message, _sentence_guess_message, _minesweeper_message,
        _best_answer_message, _battle_message, _karagah_message,
    ):
        if await responder(bot, event, chat_id, user_id, sender, text, logger):
            return True
    return False


def reset_all(chat_id=None):
    laugh_or_lose.reset_all(chat_id)
    survival.reset_all(chat_id)
    lucky_box.reset_all(chat_id)
    vampire.reset_all(chat_id)
    maemma.reset_all(chat_id)
    sentence_guess.reset_all(chat_id)
    minesweeper.reset_all(chat_id)
    best_answer.reset_all(chat_id)
    battle.reset_all(chat_id)
    karagah.reset_all(chat_id)
