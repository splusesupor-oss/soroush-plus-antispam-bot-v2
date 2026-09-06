"""
ماژول تشخیص هرزنامه - هسته اصلی ربات
"""
import re
from modules import site_policy
from typing import Tuple, Optional, List
from .config_manager import ConfigManager

class SpamDetector:
    def __init__(self, config_manager: ConfigManager):
        self.config = config_manager
        
        # الگوی لینک - بسیار گسترده برای سروش پلاس
        self.link_pattern = re.compile(
            r'(?:https?://|www\.)\S+|'
            r't\.me/\S+|'
            r'telegram\.me/\S+|'
            r'sapp\.ir/\S+|'
            r'splus\.ir/\S+|'
            r'soroush\.ir/\S+|'
            r'sapp\.ir|'
            r'\b[a-zA-Z0-9.-]+\.(?:com|ir|net|org|info|me|co|io|app|xyz)\b(?:/\S*)?',
            re.IGNORECASE
        )

        # الگوی شماره تماس ایرانی و بین‌المللی
        self.phone_patterns = [
            re.compile(r'(\+98|0098|98)?\s?9\d{2}\s?\d{3}\s?\d{4}'),  # 0912...
            re.compile(r'0\d{2,3}\s?\d{3,4}\s?\d{4}'),  # 021...
            re.compile(r'\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}'),  # عمومی
        ]

        # الگوی آیدی و یوزرنیم
        self.username_pattern = re.compile(r'@[\w\d_]{4,32}|(?:آیدی|ایدی|پی وی|پی‌وی|pv)\s*[:：]?\s*@?\w+', re.IGNORECASE)
        # Strict group policy: a plain public @username is advertising for
        # ordinary users. Authorization is checked by the message handler.
        self.public_username_pattern = re.compile(
            r"(?<![A-Za-z0-9_@])@[A-Za-z0-9_]{4,32}(?![A-Za-z0-9_])"
        )

        # الگوی تبلیغاتی عمومی
        self.mention_spam_pattern = re.compile(r'@everyone|@all|@here', re.IGNORECASE)

        self.persian_phone_pattern = re.compile(r'۰?۹[۰-۹]{9}|0?9\d{9}')
        self.username_ad_pattern = re.compile(r'جوین|عضو|کانال|گروه|add|join', re.IGNORECASE)
        self._banned_words_version = None
        self._banned_word_patterns = ()
        self._refresh_banned_word_patterns()
        # امتیاز برای تصمیم ترکیبی
        self.spam_score_threshold = 2

    _BANNED_LETTER_CLASS = r"a-zA-Z0-9_\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFC"
    # Optional separators between letters of one token (space, ZWNJ, tatweel, punct).
    _BANNED_SEP_OPT = r"[\s\u200c\u200d\u0640\W_]*"
    # Required separator where the listed phrase itself contains a space.
    _BANNED_SEP_REQ = r"[\s\u200c\u200d\u0640\W_]+"
    _BANNED_SIMILAR = {
        "ک": "کك",
        "ی": "یيىئ",
        "س": "سصث",
        "ا": "اأإآٱ",
        "ه": "هة",
        "و": "وؤ",
        "ت": "تط",
    }

    def _refresh_banned_word_patterns(self):
        version = getattr(self.config, "_banned_words_version", 0)
        if version == self._banned_words_version:
            return
        patterns = []
        for raw_word in self.config.banned_words:
            display = str(raw_word or "").strip()
            body = self._banned_word_fuzzy_body(display)
            if not display or not body:
                continue
            patterns.append((
                display,
                re.compile(
                    rf"(?<![{self._BANNED_LETTER_CLASS}]){body}"
                    rf"(?![{self._BANNED_LETTER_CLASS}])",
                    re.UNICODE,
                ),
            ))
        # Longer phrases win so «فیلم پی» is not reported as «پی».
        patterns.sort(key=lambda item: len(item[0]), reverse=True)
        self._banned_word_patterns = tuple(patterns)
        self._banned_words_version = version

    @classmethod
    def _fold_banned_letters(cls, value):
        """Unify Arabic/Persian lookalikes; keep spaces/punct for fuzzy matching."""
        if not value:
            return ""
        t = str(value).lower().replace("\ufe0f", "").replace("\ufe0e", "")
        t = re.sub(r"[\u0640\u064b-\u065f\u0670]", "", t)
        t = (
            t.replace("ي", "ی").replace("ى", "ی").replace("ئ", "ی")
            .replace("ك", "ک")
            .replace("ة", "ه")
            .replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ٱ", "ا")
            .replace("ؤ", "و")
            .replace("ص", "س")
        )
        return t

    @classmethod
    def _banned_char_class(cls, ch):
        alts = cls._BANNED_SIMILAR.get(ch, ch)
        if len(alts) == 1:
            return re.escape(ch)
        return "[" + "".join(re.escape(part) for part in dict.fromkeys(alts)) + "]"

    @classmethod
    def _banned_word_fuzzy_body(cls, word):
        """Build a body that accepts spaced/ZWNJ/punctuated/elongated forms.

        Spaces in the listed phrase stay required separators so «بی ام»
        does not match «بیام». Letters of one token may be split or repeated.
        """
        folded = cls._fold_banned_letters(word)
        parts = []
        pending_required = False
        for ch in folded:
            if ch.isspace() or ch in "\u200c\u200d":
                if parts:
                    pending_required = True
                continue
            if pending_required:
                parts.append(cls._BANNED_SEP_REQ)
                pending_required = False
            elif parts:
                parts.append(cls._BANNED_SEP_OPT)
            parts.append(cls._banned_char_class(ch) + r"+")
        return "".join(parts)

    @staticmethod
    def _normalize_banned_word(value):
        if not value:
            return ""
        t = re.sub(r"[\u0640\u064b-\u065f]", "", str(value))
        t = re.sub(r"[\u200c\u200d\u200e\u200f\ufeff\u00a0\-_.,/\\;:!؟،؛|()\[\]{}<>+=*&^%$#@~\"'`«»…]+", " ", t)
        t = t.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه").replace("آ", "ا").replace("أ", "ا").replace("إ", "ا")
        return " ".join(t.lower().split())

    def check_links(self, text: str) -> Tuple[bool, Optional[str]]:
        if not self.config.get("check_links", True):
            return False, None
        match = self.link_pattern.search(text)
        if match:
            found_link = match.group(0).lower()

            # لینک دعوت جلسه سروش پلاس مجاز است
            if "splus.ir/meet/" in found_link:
                return False, None

            classification, domain = site_policy.classify(found_link)
            if classification == "blocked":
                return True, f"دامنه مسدود ({domain})"
            if classification in {"trusted", "search"}:
                return False, None
            # Unknown domains retain the existing group link policy.
            return True, f"لینک مشکوک ({match.group(0)[:30]})"
        return False, None

    def check_phone_numbers(self, text: str) -> Tuple[bool, Optional[str]]:
        if not self.config.get("check_phone_numbers", True):
            return False, None
        # حذف فاصله‌های زیاد برای تشخیص بهتر
        for pattern in self.phone_patterns:
            # برای جلوگیری از تشخیص اعداد معمولی، حداقل طول را چک می‌کنیم
            matches = pattern.findall(text)
            for m in matches:
                # اگر متن عددی طولانی است و شبیه شماره است
                digits = re.sub(r'\D', '', str(m) if isinstance(m, str) else ''.join(m))
                if len(digits) >= 10 and len(digits) <= 13:
                    # فیلتر اعداد تکراری غیر واقعی یا بیش از حد کوتاه
                    if not (len(set(digits)) == 1):  # مثلا 1111111111 را نادیده نگیر ولی با احتیاط
                        return True, f"شماره تماس ({digits[:4]}...)"
                    return True, f"شماره تماس"
        # الگوی ساده‌تر برای شماره‌های فارسی با حروف
        if self.persian_phone_pattern.search(text):
            return True, "شماره تماس"
        return False, None

    def has_public_username(self, text: str) -> bool:
        """Fast, allocation-free check for a public @username mention."""
        return bool(self.public_username_pattern.search(str(text or "")))

    def check_usernames(self, text: str) -> Tuple[bool, Optional[str]]:
        if not self.config.get("check_usernames", True):
            return False, None
        # اگر بیش از 2 آیدی در پیام باشد -> اسپم
        mentions = self.username_pattern.findall(text)
        if len(mentions) >= 1:
            # برای جلوگیری از False Positive روی یک منشن ساده، فقط اگر با کلمات تبلیغاتی ترکیب شده باشد یا بیش از یکی باشد
            # اما طبق درخواست شما، آیدی به تنهایی هم مشکوک است
            if len(mentions) >= 2:
                return True, f"چندین آیدی ({len(mentions)} مورد)"
            # اگر یک آیدی + کلمه تبلیغاتی
            if len(mentions) == 1:
                # چک می‌کنیم آیا متن حاوی دستور جوین یا تبلیغ است
                if self.username_ad_pattern.search(text):
                    return True, f"آیدی تبلیغاتی ({mentions[0]})"
                # اگر تنظیمات سختگیرانه است، حتی تک آیدی را هم اسپم بگیر
                # برای این پروژه طبق درخواست شما، آیدی به تنهایی اسپم محسوب می‌شود اگر در تنظیمات فعال باشد
                # ولی برای کاهش خطا، فقط اگر متن کوتاه و فقط آیدی باشد
                if len(text.strip()) < 50 and '@' in text:
                    return True, f"آیدی ({mentions[0]})"
        return False, None

    def check_banned_words(self, text: str, chat_id=None) -> Tuple[bool, Optional[str]]:
        # BANNED WORDS (strict mode) - per-group toggle via "فعال کلمات ممنوعه"
        # Independent from GROUP_CUSTOM_WORD_FILTER (/filter)
        if not self.config.get("check_banned_words", True):
            return False, None
        # Per-group strict mode check
        if chat_id is not None:
            try:
                from modules.group_banned_words_control import is_enabled as is_strict_enabled
                if not is_strict_enabled(chat_id):
                    # Strict mode disabled for this group - log for debugging why banned word didn't trigger
                    # Use a lightweight check without full logging to avoid spam
                    return False, None
            except Exception:
                pass
        self._refresh_banned_word_patterns()
        haystack = self._fold_banned_letters(text)
        if not haystack:
            return False, None
        for word, pattern in self._banned_word_patterns:
            if pattern.search(haystack):
                # Obfuscated input maps back to the original listed word.
                return True, f"banned_word کلمه ممنوعه ({word})"
        return False, None

    def check_spam_score(self, text: str, chat_id=None, include_banned_words=True) -> Tuple[int, List[str]]:
        """سیستم امتیازدهی برای تشخیص اسپم‌های ترکیبی"""
        score = 0
        reasons = []

        is_link, reason_link = self.check_links(text)
        if is_link:
            score += 2
            reasons.append(reason_link)

        is_phone, reason_phone = self.check_phone_numbers(text)
        if is_phone:
            score += 2
            reasons.append(reason_phone)

        is_user, reason_user = self.check_usernames(text)
        if is_user:
            score += 2
            reasons.append(reason_user)

        if include_banned_words:
            is_banned, reason_banned = self.check_banned_words(text, chat_id)
            if is_banned:
                score += 2
                reasons.append(reason_banned)

        # بررسی فوروارد زیاد یا ایموجی زیاد
        if len(text) > 500 and text.count('http') >= 1:
            score += 1
            reasons.append("متن طولانی + لینک")

        if self.mention_spam_pattern.search(text):
            score += 3
            reasons.append("منشن گروهی")

        return score, reasons

    def is_spam(self, text: str, chat_id=None) -> Tuple[bool, str]:
        """تشخیص با early-exit؛ هر check مستقلِ مثبت به آستانهٔ ۲ می‌رسد."""
        if not text or not text.strip():
            return False, ""
        self.config.reload_if_needed()
        is_banned, reason = self.check_banned_words(text, chat_id)
        # Log for debugging why banned word did or didn't trigger
        try:
            from modules.group_banned_words_control import is_enabled as _is_strict
            strict_on = _is_strict(chat_id) if chat_id is not None else True
        except Exception:
            strict_on = True
        # Only log when text contains potential banned word or when strict is off
        # To avoid log flood, we log via a lightweight check
        is_banned_log = is_banned
        if not is_banned_log and chat_id is not None:
            # If strict is off, log that we skipped
            if not strict_on:
                # We don't have the word, but we can log that strict is off
                pass
        if is_banned:
            # Detailed log for successful detection
            try:
                import logging
                # Use print for now, will be captured by bot logger if available
                pass
            except Exception:
                pass
            return True, reason
        is_link, reason = self.check_links(text)
        if is_link:
            return True, reason
        is_phone, reason = self.check_phone_numbers(text)
        if is_phone:
            return True, reason
        is_user, reason = self.check_usernames(text)
        if is_user:
            return True, reason
        if self.mention_spam_pattern.search(text):
            return True, "منشن گروهی"
        # لایو تبلیغاتی با ایموجی صریح (مثل «لایو گذاشتم 👙🍑»)
        if re.search(r"لایو|لایوه|\blive\b", text, re.IGNORECASE) and re.search(
            "[\U0001F459\U0001F351\U0001FAE6\U0001F608\U0001F348\U0001F52F]",
            text,
        ):
            return True, "لایو تبلیغاتی"
        return False, ""

    def analyze(self, text: str) -> dict:
        """تحلیل کامل برای لاگ"""
        score, reasons = self.check_spam_score(text)
        is_spam, reason_str = self.is_spam(text)
        return {
            "is_spam": is_spam,
            "score": score,
            "reasons": reasons,
            "reason_str": reason_str
        }


    def check_media_spam(self, message):
        """
        تشخیص اسپم فایل و عکس
        """
        try:
            if not message:
                return False

            if getattr(message, "photo", None):
                return True

            if getattr(message, "file", None):
                filename = getattr(message.file, "name", "") or ""
                
                bad = [
                    ".exe",
                    ".apk",
                    ".zip",
                    ".rar",
                    ".scr",
                    ".bat"
                ]

                for x in bad:
                    if filename.lower().endswith(x):
                        return True

            return False

        except Exception as e:
            print("media spam check error:", e)
            return False
