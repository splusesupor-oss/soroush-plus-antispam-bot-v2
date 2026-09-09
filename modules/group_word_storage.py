
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


def add_group_word(group_id, word):
    data = load_words()

    gid = str(group_id)
    word = word.strip().lower()

    if not word:
        return False

    if gid not in data:
        data[gid] = []

    if word in data[gid]:
        return False

    data[gid].append(word)
    save_words(data)

    return True


def remove_group_word(group_id, word):
    data = load_words()

    gid = str(group_id)
    word = word.strip().lower()

    if gid in data and word in data[gid]:
        data[gid].remove(word)
        save_words(data)
        return True

    return False


def get_group_words(group_id):
    data = load_words()
    return data.get(str(group_id), [])
