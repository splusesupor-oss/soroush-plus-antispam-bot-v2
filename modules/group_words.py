import json
from pathlib import Path

from modules.runtime_paths import runtime_config_file

# per-instance: هر instance (main/bot2/bot3) فایل خودش را می‌خواند/می‌نویسد.
FILE = Path(runtime_config_file("group_banned_words.json"))


def load_words():
    if not FILE.exists():
        return {}

    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except:
        return {}


def save_words(data):
    FILE.parent.mkdir(exist_ok=True)
    FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def add_word(group_id, word):
    data = load_words()
    gid = str(group_id)

    if gid not in data:
        data[gid] = []

    word = word.strip().lower()

    if word not in data[gid]:
        data[gid].append(word)
        save_words(data)
        return True

    return False


def remove_word(group_id, word):
    data = load_words()
    gid = str(group_id)

    word = word.strip().lower()

    if gid in data and word in data[gid]:
        data[gid].remove(word)
        save_words(data)
        return True

    return False


def check_word(group_id, text):
    data = load_words()
    gid = str(group_id)

    if gid not in data:
        return None

    text = text.lower()

    for word in data[gid]:
        if word in text:
            return word

    return None
