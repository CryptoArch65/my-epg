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

    # Scope the timestamp replacement strictly to import_regionals(). K1 and
    # every other MTS importer keep their existing timestamp handling.
    if "start = regional_stamp(item[\"start\"])" not in content:
        regional_start = content.find("def import_regionals(root):")
        k1_start = content.find("\ndef supplement_k1(root):", regional_start)
        if regional_start < 0 or k1_start < 0:
            raise SystemExit("Could not locate import_regionals() boundaries")

        prefix = content[:regional_start]
        regional = content[regional_start:k1_start]
        suffix = content[k1_start:]

        old_start = 'start = stamp(item["start"])'
        old_stop = 'stop = stamp(item["end"])'
        if regional.count(old_start) != 1 or regional.count(old_stop) != 1:
            raise SystemExit("Regional timestamp statements changed unexpectedly")

        regional = regional.replace(
            old_start, 'start = regional_stamp(item["start"])', 1
        )
        regional = regional.replace(
            old_stop, 'stop = regional_stamp(item["end"])', 1
        )
        content = prefix + regional + suffix
        changed = True

    if changed:
        PATH.write_text(content, encoding="utf-8")
        print("Patched MTS regional importer: local clock + Newsmax provider alias")
    else:
        print("MTS regional importer already patched")


if __name__ == "__main__":
    main()
