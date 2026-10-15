#!/usr/bin/env python3
"""Log health checker for the Soroush bot (B1 / B2 / B3).

Reports, without modifying anything:

* which instance and which log directory are actually in use;
* duplicate handlers on the same logger, and two loggers writing one file;
* log files that exceed the rotation limit;
* rotated files that should already have been purged;
* whether any other instance's log/config directory is reachable from here;
* leaked secrets inside the current log files (masked output only).

Exit code is 0 when healthy, 1 when problems were found, 2 when the module
could not be imported at all — so it is safe to use in scripts.

Usage::

    python3 tools/log_health.py            # human readable
    python3 tools/log_health.py --json     # machine readable
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# The instance must be decided before runtime_paths is imported.
if not os.environ.get("BOT_INSTANCE"):
    try:
        marker = (_ROOT / ".bot_instance").read_text(encoding="utf-8").strip()
        if marker:
            os.environ["BOT_INSTANCE"] = marker
    except OSError:
        pass

from modules import secret_guard  # noqa: E402
from modules import instance_guard  # noqa: E402

secret_guard.bootstrap(_ROOT)

from modules.logger_module import health  # noqa: E402
from modules.runtime_paths import (  # noqa: E402
    DATA_DIR, INSTANCE_NAME, LOG_DIR, describe,
)


def _scan_for_secrets(directory: Path, limit_bytes: int = 4 * 1024 * 1024):
    """Return (file, line_number) hits; values are never printed."""
    hits = []
    if not directory.exists():
        return hits
    for path in sorted(directory.glob("*.log*")):
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                if size > limit_bytes:
                    handle.seek(-limit_bytes, os.SEEK_END)
                text = handle.read().decode("utf-8", "replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if secret_guard.mask(line) != line:
                hits.append({"file": path.name, "line": number})
                if len(hits) >= 20:
                    return hits
    return hits


def _foreign_directories():
    """Existing sibling data directories of the other bots (read-only check)."""
    found = []
    base = Path.home() / ".local" / "share"
    try:
        candidates = sorted(base.glob("soroush-bot*"))
    except OSError:
        return found
    for path in candidates:
        if path.resolve() == Path(DATA_DIR).resolve():
            continue
        found.append(str(path))
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true",
                        help="print the report as JSON")
    args = parser.parse_args(argv)

    try:
        report = health()
    except Exception as error:  # pragma: no cover - import failure path
        print(f"log_health: cannot start logging runtime: {error!r}",
              file=sys.stderr)
        return 2

    paths = describe()
    report["paths"] = paths
    report["marker"] = instance_guard.read_marker()
    report["secrets_registered"] = secret_guard.registered_count()
    report["secret_leaks"] = _scan_for_secrets(Path(LOG_DIR))
    report["other_instances"] = _foreign_directories()

    if report["secret_leaks"]:
        report["problems"].append(
            f"possible secret material in {len(report['secret_leaks'])} log line(s)"
        )
    if report["marker"] not in (None, INSTANCE_NAME):
        report["problems"].append(
            f"marker {report['marker']!r} disagrees with effective instance "
            f"{INSTANCE_NAME!r}"
        )
    if paths.get("private") is False:
        report["problems"].append(
            "runtime data is NOT in a private per-instance directory "
            "(data lies inside the source tree)"
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"instance          : {report['instance']}")
        print(f"marker            : {report.get('marker')}")
        print(f"log dir           : {report['expected_log_dir']}")
        print(f"data dir          : {paths.get('data_dir')}")
        print(f"rotation          : {report['max_bytes']} bytes x "
              f"{report['backups']} backups, retention "
              f"{report['retention_days']} days")
        print(f"console level     : {report['console_level']} "
              f"(verbose={report['verbose']})")
        print(f"secrets registered: {report['secrets_registered']}")
        print(f"log files         : {len(report['files'])}")
        for item in report["files"]:
            flag = " (rotated)" if item["rotated"] else ""
            print(f"  - {item['name']}: {item['size']} bytes{flag}")
        if report["other_instances"]:
            print("other instances on this device (not touched, read-only):")
            for item in report["other_instances"]:
                print(f"  - {item}")
        if report["problems"]:
            print("\nPROBLEMS:")
            for problem in report["problems"]:
                print(f"  ! {problem}")
        else:
            print("\nOK: no logging or isolation problem found.")

    return 1 if report["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
