"""رگرسیون تقویت guard موجود نام تبلیغاتی."""
from types import SimpleNamespace

from modules.ad_name_detector import reason


def user(name="", username=None, last_name=None):
    return SimpleNamespace(first_name=name, last_name=last_name, username=username)


def test_exact_new_terms_and_emojis():
    terms = (
        "💦", "سکس", "🌈", "👄", "💋", "🤤", "😰", "🥵", "🍑",
        "بیوگرافی", "فیلم", "زوری", "کانال", "گروه", "یکی بیاد",
        "خانوم", "پسر", "دختر",
    )
    for term in terms:
        assert reason(user(term)) is not None, term


def test_sex_and_biography_broken_stretched_and_repeated():
    samples = (
        "س ک س", "س‌ک‌س", "سـکــس", "سسسکککسسس", "س.ک-س",
        "ب ی و گ ر ا ف ی", "بـیــوگرافی", "بیییوگگگرافففی",
        "ب‌ـی.و/گ_ر-ا ف ی", "تبلیغ س‌کــکس و ب ی و گ ر ا ف ی",
    )
    for sample in samples:
        assert reason(user(sample)) is not None, sample


def test_other_terms_common_variations_and_username():
    samples = (
        user("ی ک ی  ب ی ا د"), user("کــــانــــال"), user("دخخختر"),
        user("پ.س.ر"), user("گ‌ـر و ه"), user(username="film_کانال_خوب"),
        user("خانننوم"), user("فففیلم"),
    )
    for sample in samples:
        assert reason(sample) is not None, sample


def test_mixed_words_and_emoji_are_detected():
    assert reason(user("علی 🌈 کانال فیلم")) is not None
    assert reason(user("نام معمولی", username="bio_بـیـوگرافی")) is not None


def test_legitimate_names_do_not_false_positive():
    allowed = (
        user("علی", "ali_rezaei", "رضایی"),
        user("سارا", "sara_ahmadi", "احمدی"),
        user("محمدرضا", "mohammadreza", "حسینی"),
        user("پیمان", "peyman"), user("کسری", "kasra"),
        user("بیژن", "bijan"), user("گروسی", "garousi"),
    )
    for sample in allowed:
        assert reason(sample) is None, sample
