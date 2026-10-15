import unittest

import modules.name_family as game


class NameFamilyValidationTests(unittest.TestCase):
    def setUp(self):
        # 🐛 این تست‌ها قبلاً ``game.add`` را patch می‌کردند؛ آن تابع دیگر وجود
        # ندارد. در طراحی فعلی ماژول «پرداخت» نمی‌کند: امتیاز هر بازیکن را در
        # حالت دور ذخیره می‌کند و پرداخت سکه توسط هندلر از API اقتصاد انجام
        # می‌شود (به کامنت ابتدای modules/name_family.py نگاه کنید).
        # بنابراین ``self.awards`` همان امتیازی را ثبت می‌کند که ماژول واقعاً
        # در حالت دور نوشته است؛ هیچ رفتار ساختگی‌ای اضافه نشده.
        self.original_learning = game.record_learning
        self._real_submit = game.submit
        self.awards = []
        self.learning = []

        def recording_submit(chat_id, user_id, name, text, *args, **kwargs):
            result = self._real_submit(
                chat_id, user_id, name, text, *args, **kwargs)
            entry = ((game._ACTIVE.get(chat_id) or {}).get("answers")
                     or {}).get(str(user_id))
            if result is not None and entry is not None:
                self.awards.append((chat_id, user_id, entry.get("points")))
            return result

        game.submit = recording_submit
        game.record_learning = lambda *args, **kwargs: (
            self.learning.append((args, kwargs)) or {"status": "learning"}
        )
        # 🌐 مسیر تأیید بیرونی (ویکی‌داده/ویکی‌پدیا) درخواست شبکه می‌زند؛ در
        # تست به‌طور پیش‌فرض خاموش می‌شود تا نتیجه به اینترنت وابسته نباشد
        # (پیش‌تر همین باعث امتیازهای شناور ۵۰/۶۰ و شکست‌های تصادفی می‌شد).
        # تستِ مخصوص این مسیر خودش با stub آن را می‌سنجد.
        self._real_external = game._external_confirms_category
        game._external_confirms_category = lambda *args, **kwargs: None
        # 🐛 reset_all() خودِ ماژول: بدون آن، _FINISHED_ROUNDS بین تست‌ها باقی
        # می‌ماند و شناسه‌های دورِ واقعی با شناسه‌های ساختگی برخورد می‌کردند
        # (finish() بی‌دلیل «already_finished» می‌شد و _ACTIVE پاک نمی‌شد).
        game.reset_all()

    def tearDown(self):
        game.submit = self._real_submit
        game.record_learning = self.original_learning
        game._external_confirms_category = self._real_external
        game.reset_all()

    def test_external_confirmation_uses_stubbed_source_without_network(self):
        """مسیر «تأیید بیرونی» بدون شبکه ولی با منطق واقعی سنجیده می‌شود.

        در تولید، این مسیر از ویکی‌داده/ویکی‌پدیا پاسخ می‌گیرد؛ اینجا فقط
        خودِ تابع شبکه با یک stub جایگزین شده تا تست آفلاین و قطعی بماند.
        انتظار: ۱۰ امتیاز و ثبت منبع در لاگ دسته‌بندی.
        """
        game._external_confirms_category = lambda *args, **kwargs: "wikidata"

        class Logger:
            def __init__(self):
                self.lines = []

            def log_info(self, line):
                self.lines.append(line)

        logger = Logger()
        game._ACTIVE[100] = {"round_id": 1, "letter": "پ", "answers": {}}
        answers = "\n".join((
            "پپپپپ", "نمیدونم", "نمیدونم", "نمیدونم", "نمیدونم", "نمیدونم", "نمیدونم",
        ))
        self.assertEqual(game.submit(100, 7, "کاربر", answers, logger=logger), 10)
        lines = self.category_lines(logger)
        self.assertIn("category=نام", lines[0])
        self.assertIn("score=10", lines[0])
        self.assertIn("source=wikidata", lines[0])

    @staticmethod
    def category_lines(logger):
        """فقط خطوط دسته‌بندی (هفت‌تا) را برمی‌گرداند.

        ماژول در هر submit خطوط دیگری هم می‌نویسد (ENTER، BATCH، SCORE،
        STORE). تست‌ها به ترتیبِ همان هفت خط دسته‌بندی کار دارند، نه به حجم
        کل لاگ؛ پس به‌جای شمارهٔ خط ثابت، بر اساس محتوا فیلتر می‌کنیم.
        """
        return [line for line in logger.lines
                if "category=" in line and "raw_answer=" in line]

    @staticmethod
    def valid_answers():
        return "\n".join((
            "فریبا", "فری", "فردوس", "فندق", "فرغون", "فیل", "فرهاد",
        ))

    def force_round(self, round_id):
        game._ACTIVE[100] = {
            "round_id": round_id,
            "letter": "ف",
            "answers": {},
        }

    def test_valid_category_answers_receive_seventy_points(self):
        self.force_round(1)
        self.assertEqual(game.submit(100, 7, "کاربر", self.valid_answers()), 70)
        self.assertEqual(self.awards, [(100, 7, 70)])

    def test_database_coverage_and_full_score_for_every_playable_letter(self):
        # Every alphabet letter is classified; only fully covered letters are selectable.
        for letter in game.LETTERS:
            covered = all(game.LETTER_COVERAGE[letter].values())
            has_unique_round = game.ROUND_EXAMPLES.get(letter) is not None
            self.assertEqual(letter in game.PLAYABLE_LETTERS, covered and has_unique_round)

        for index, letter in enumerate(game.PLAYABLE_LETTERS):
            answers = game.ROUND_EXAMPLES[letter]
            self.assertEqual(len({game._normalize(answer) for answer in answers}), 7)
            chat_id = 1000 + index
            game._ACTIVE[chat_id] = {
                "round_id": index + 1,
                "letter": letter,
                "answers": {},
            }
            self.assertEqual(
                game.submit(chat_id, index + 1, "کاربر", "\n".join(answers)),
                70,
            )
            self.assertFalse(game._validate_answer("نام", letter, letter + "چیچی"))

    def test_start_draws_only_fully_covered_letters(self):
        game._REMAINING_LETTERS.clear()
        drawn = []
        for _ in game.PLAYABLE_LETTERS:
            round_state = game.start(500)
            drawn.append(round_state["letter"])
            game.finish(500)
        self.assertEqual(set(drawn), set(game.PLAYABLE_LETTERS))
        self.assertTrue(set(drawn).isdisjoint(game.UNPLAYABLE_LETTERS))

    def test_p_inputs_are_scored_per_category_and_emit_raw_normalized_logs(self):
        class Logger:
            def __init__(self):
                self.lines = []

            def log_info(self, line):
                self.lines.append(line)

        first = ("پریا", "پروینی", "پل دختر", "پرتقال", "پر", "پشه", "نمیدونم")
        second = ("پونه", "پناهی", "پاریس", "پرتغالی", "پارو", "پشه", "پالت")
        logger = Logger()
        game._ACTIVE[100] = {"round_id": 1, "letter": "پ", "answers": {}}
        self.assertEqual(game.submit(100, 7, "کاربر", "\n".join(first), logger=logger), 60)
        lines = self.category_lines(logger)
        self.assertEqual(len(lines), 7)
        self.assertIn(
            "category=نام raw_answer=پریا normalized_answer=پریا letter=پ source=database reason=database_match valid=True score=10",
            lines[0],
        )
        self.assertIn(
            "category=خواننده raw_answer=نمیدونم normalized_answer=نمیدونم letter=پ source=none reason=invalid valid=False score=0",
            lines[6],
        )

        game._ACTIVE[100] = {"round_id": 2, "letter": "پ", "answers": {}}
        self.assertEqual(game.submit(100, 8, "کاربر", "\n".join(second)), 70)

    def test_jim_example_scores_each_category_independently(self):
        answers = ("جهان", "جوادی", "جیرفت", "جمبو", "جعبه", "جغد", "جهان")
        game._ACTIVE[100] = {
            "round_id": 1,
            "letter": "ج",
            "answers": {},
        }
        expected_valid = (True, True, True, False, True, True, True)
        self.assertEqual(
            tuple(
                game._validate_answer(category, "ج", answer)
                for category, answer in zip(game.CATEGORIES, answers)
            ),
            expected_valid,
        )
        # "جهان" appears twice; the second occurrence cannot earn a second score.
        self.assertEqual(game.submit(100, 7, "کاربر", "\n".join(answers)), 50)
        self.assertEqual(self.awards, [(100, 7, 50)])

    def test_duplicate_answer_is_not_scored_twice(self):
        game._ACTIVE[100] = {"round_id": 1, "letter": "ج", "answers": {}}
        answers = "\n".join((
            "جهان", "جوادی", "جیرفت", "جک فروت", "جعبه", "جغد", "جهان",
        ))
        self.assertEqual(game.submit(100, 7, "کاربر", answers), 60)

    def test_each_category_contributes_exactly_ten_points(self):
        answers = self.valid_answers().splitlines()
        self.force_round(1)
        self.assertEqual(game.submit(100, 7, "کاربر", "\n".join(answers[:4] + ["فوفوف"] * 3)), 40)
        self.force_round(2)
        self.assertEqual(game.submit(100, 8, "کاربر", "\n".join(answers[:2] + ["فوفوف"] * 5)), 20)

    def test_zah_example_scores_twenty_without_zeroing_other_categories(self):
        class Logger:
            def __init__(self):
                self.lines = []

            def log_info(self, line):
                self.lines.append(line)

        logger = Logger()
        game._ACTIVE[100] = {
            "round_id": 1,
            "letter": "ظ",
            "answers": {},
        }
        answers = "\n".join((
            "ظاتمه", "ظفري", "نمی‌دونم", "نمی دانم", "ظرف", "نمیدونم", "نمی‌دونم",
        ))
        self.assertEqual(game.submit(100, 7, "کاربر", answers, logger=logger), 20)
        lines = self.category_lines(logger)
        self.assertIn("category=نام raw_answer=ظاتمه normalized_answer=ظاتمه letter=ظ source=learning reason=insufficient_confidence valid=False score=0", lines[0])
        self.assertIn("category=فامیل raw_answer=ظفري normalized_answer=ظفری letter=ظ source=database reason=database_match valid=True score=10", lines[1])
        self.assertIn("category=وسیله raw_answer=ظرف normalized_answer=ظرف letter=ظ source=database reason=database_match valid=True score=10", lines[4])
        self.assertEqual(len(lines), 7)

    def test_persian_normalization_and_empty_variants(self):
        self.assertEqual(game._normalize("  نمی‌دونم  "), "نمیدونم")
        self.assertEqual(game._normalize("ظفري"), "ظفری")
        self.assertEqual(game._normalize("فیروز  کوه"), "فیروز کوه")
        self.assertFalse(game._validate_answer("نام", "ن", "نمی‌دونم"))
        self.assertFalse(game._validate_answer("نام", "ن", "نمی دانم"))

    def test_yeh_examples_score_fifty_and_ten_independently(self):
        game._ACTIVE[100] = {
            "round_id": 1,
            "letter": "ی",
            "answers": {},
        }
        fifty_answers = "\n".join((
            "یسنا", "یاوری", "یزد", "نمیدونم", "یویو", "یوزپلنگ", "نمیدونم",
        ))
        self.assertEqual(game.submit(100, 7, "کاربر", fifty_answers), 50)

        game._ACTIVE[100] = {
            "round_id": 2,
            "letter": "ی",
            "answers": {},
        }
        ten_answers = "\n".join((
            "یارو", "یاوری", "نمیدونم", "نمیدونم", "یخ", "نمیدونم", "نمیدونم",
        ))
        self.assertEqual(game.submit(100, 8, "کاربر", ten_answers), 10)

    def test_vahids_partial_answers_score_thirty_and_log_each_category(self):
        class Logger:
            def __init__(self):
                self.lines = []

            def log_info(self, line):
                self.lines.append(line)

        logger = Logger()
        game._ACTIVE[100] = {
            "round_id": 1,
            "letter": "و",
            "answers": {},
        }
        answers = "\n".join((
            "وحید", "وحیدی", "ورامین", "نمی‌دونم", "وینچستر", "نمی‌دونم", "وحید",
        ))
        self.assertEqual(game.submit(100, 7, "کاربر", answers, logger=logger), 30)
        lines = self.category_lines(logger)
        self.assertIn("category=نام raw_answer=وحید normalized_answer=وحید letter=و source=database reason=database_match valid=True score=10", lines[0])
        self.assertIn("category=فامیل raw_answer=وحیدی normalized_answer=وحیدی letter=و source=database reason=database_match valid=True score=10", lines[1])
        self.assertIn("category=شهر raw_answer=ورامین normalized_answer=ورامین letter=و source=database reason=database_match valid=True score=10", lines[2])
        self.assertIn("category=میوه raw_answer=نمی‌دونم normalized_answer=نمیدونم letter=و source=none reason=invalid valid=False score=0", lines[3])
        self.assertEqual(len(lines), 7)

    def test_unknown_answer_is_pending_and_defaults_to_zero(self):
        class Logger:
            def __init__(self):
                self.lines = []

            def log_info(self, line):
                self.lines.append(line)

        logger = Logger()
        game._ACTIVE[100] = {"round_id": 1, "letter": "ن", "answers": {}}
        answers = "\n".join((
            "نازنین", "نادری", "نیکشهر", "نارنج", "نی", "نهنگ", "ناصر زینلی",
        ))
        self.assertEqual(game.submit(100, 7, "کاربر", answers, logger=logger), 60)
        self.assertEqual(len(self.learning), 1)
        self.assertEqual(self.learning[0][0][0:4], ("شهر", "ن", "نیکشهر", "نیکشهر"))
        lines = self.category_lines(logger)
        self.assertIn("source=learning reason=insufficient_confidence valid=False score=0", lines[2])

    def test_unknown_answer_never_scores_before_learning(self):
        game._ACTIVE[100] = {"round_id": 1, "letter": "ن", "answers": {}}
        answers = "\n".join((
            "نمنمن", "نادری", "نیشابور", "نارنج", "نی", "نهنگ", "ناصر زینلی",
        ))
        self.assertEqual(game.submit(100, 7, "کاربر", answers), 60)
        self.assertEqual(len(self.learning), 1)


    def test_fabricated_answers_receive_zero_points(self):
        self.force_round(1)
        fabricated = "\n".join((
            "فوفوف", "فچچس", "فسوسس", "فغغغ", "فپپپ", "فززز", "فککک",
        ))
        self.assertEqual(game.submit(100, 7, "کاربر", fabricated), 0)
        self.assertEqual(self.awards, [(100, 7, 0)])

    def test_category_mismatch_and_non_letters_are_invalid(self):
        self.assertFalse(game._validate_answer("شهر", "ف", "فریبا"))
        self.assertFalse(game._validate_answer("نام", "ف", "فریبا123"))
        self.assertTrue(game._validate_answer("نام", "ف", "فریبا"))

    def test_only_seven_raw_nonempty_lines_are_accepted(self):
        self.assertEqual(game._parse_answers(self.valid_answers()), self.valid_answers().splitlines())
        self.assertIsNone(game._parse_answers("پیام عادی"))
        self.assertIsNone(game._parse_answers(self.valid_answers().replace("\n", " | ")))
        self.assertIsNone(game._parse_answers(self.valid_answers().replace("\n", "،")))
        labelled = "\n".join(
            f"{category}: {answer}"
            for category, answer in zip(game.CATEGORIES, self.valid_answers().splitlines())
        )
        self.assertIsNone(game._parse_answers(labelled))
        # رفتار مستندشدهٔ فعلی (به docstring ماژول نگاه کنید): خط خالی و
        # newline پایانی «تحمل» می‌شوند، چون کیبورد موبایل مرتب آن‌ها را
        # اضافه می‌کند و ردکردن‌شان پاسخ‌های معتبر را بی‌صدا حذف می‌کرد.
        self.assertEqual(
            game._parse_answers(self.valid_answers() + "\n"),
            self.valid_answers().splitlines(),
        )
        self.assertEqual(
            game._parse_answers(self.valid_answers().replace("\n", "\n\n")),
            self.valid_answers().splitlines(),
        )
        # ولی هشت پاسخِ واقعی رد می‌شود: قرارداد «هفت پاسخ» تغییر نکرده.
        self.assertIsNone(
            game._parse_answers(self.valid_answers() + "\nهشتم"))

    def test_unrelated_messages_do_not_create_a_submission(self):
        self.force_round(1)
        self.assertIsNone(game.submit(100, 7, "کاربر", "سلام ربات"))
        self.assertEqual(game._ACTIVE[100]["answers"], {})
        self.assertEqual(self.awards, [])

    def test_duplicate_submission_does_not_add_points_twice(self):
        self.force_round(1)
        self.assertEqual(game.submit(100, 7, "کاربر", self.valid_answers()), 70)
        self.assertIsNone(game.submit(100, 7, "کاربر", "فوفوف\nفوفوف\nفوفوف\nفوفوف\nفوفوف\nفوفوف\nفوفوف"))
        self.assertEqual(self.awards, [(100, 7, 70)])

    def test_scores_do_not_transfer_between_rounds(self):
        self.force_round(1)
        game.submit(100, 7, "کاربر", self.valid_answers())
        self.assertEqual(game.finish(100)[0]["points"], 70)
        self.force_round(2)
        self.assertEqual(game.submit(100, 7, "کاربر", "فوفوف\nفوفوف\nفوفوف\nفوفوف\nفوفوف\nفوفوف\nفوفوف"), 0)
        finished = game.finish(100)
        self.assertEqual(finished[0]["round_id"], 2)
        self.assertEqual(finished[0]["points"], 0)


if __name__ == "__main__":
    unittest.main()
