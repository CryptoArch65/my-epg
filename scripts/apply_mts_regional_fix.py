#!/usr/bin/env python3
"""Permanently patch the Serbian MTS regional importer.

MTS returns regional programme clock values with a trailing Z even though those
clock values match the broadcasters' Europe/Belgrade local schedules. Treating
that Z as real UTC shifts the guide two hours late during CEST.
"""

from pathlib import Path

PATH = Path("scripts/import_mts_serbia_epg.py")


def main():
    content = PATH.read_text(encoding="utf-8")
    changed = False

    old_alias = '        "aliases": ("Newsmax_Balkans", "Newsmax Balkans"),'
    new_alias = '        "aliases": ("Newsmax_Balkans", "Newsmax Balkans", "newsmaxbalkans.rs"),'
    if new_alias not in content:
        if content.count(old_alias) != 1:
            raise SystemExit("Newsmax alias block changed unexpectedly")
        content = content.replace(old_alias, new_alias, 1)
        changed = True

    regional_function = '''def regional_stamp(value):
    """Interpret MTS regional ISO clock values as Europe/Belgrade local time.

    MTS currently appends ``Z`` to values such as 10:00 even though broadcaster
    schedules show that 10:00 is the intended Serbian local clock time. Keeping
    the Z would turn 10:00 into 12:00 during CEST.
    """
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            local = __import__("datetime").datetime.fromisoformat(text[:-1])
            if local.tzinfo is not None:
                local = local.replace(tzinfo=None)
            local = local.replace(tzinfo=ZONE)
            return local.strftime("%Y%m%d%H%M%S %z")
    return stamp(value)


'''
    if "def regional_stamp(value):" not in content:
        marker = "def parse_xmltv_time(value):\n"
        if content.count(marker) != 1:
            raise SystemExit("parse_xmltv_time marker changed unexpectedly")
        content = content.replace(marker, regional_function + marker, 1)
        changed = True

    old_stamp = '''                    start = stamp(item["start"])
                    stop = stamp(item["end"])
'''
    new_stamp = '''                    start = regional_stamp(item["start"])
                    stop = regional_stamp(item["end"])
'''
    if new_stamp not in content:
        if content.count(old_stamp) < 2:
            raise SystemExit("Expected regional/K1 stamp blocks were not found")
        # Only the first block belongs to import_regionals(). K1 keeps its own
        # existing timestamp behavior because its primary schedule is official.
        content = content.replace(old_stamp, new_stamp, 1)
        changed = True

    if changed:
        PATH.write_text(content, encoding="utf-8")
        print("Patched MTS regional importer: local clock + Newsmax provider alias")
    else:
        print("MTS regional importer already patched")


if __name__ == "__main__":
    main()
