#!/usr/bin/env python3
"""Keep the Serbian MTS regional importer on standard ISO/UTC timestamps.

The MTS API returns ISO timestamps with a trailing ``Z``. ``Z`` means UTC and
must not be reinterpreted as a Europe/Belgrade local clock. XMLTV/TiviMate can
then convert the timestamp to the viewer's local timezone normally.

This patcher also keeps the safe Newsmax playlist alias, but deliberately does
not create aliases for known-wrong provider IDs such as Pešter's Prva ID or
TV AS's Pink Show ID.
"""

import re
from pathlib import Path

PATH = Path("scripts/import_mts_serbia_epg.py")


def main():
    content = PATH.read_text(encoding="utf-8")
    original = content

    # Keep the unique, valid Newsmax playlist ID available in the XMLTV guide.
    old_alias = '        "aliases": ("Newsmax_Balkans", "Newsmax Balkans"),'
    new_alias = '        "aliases": ("Newsmax_Balkans", "Newsmax Balkans", "newsmaxbalkans.rs"),'
    if new_alias not in content and old_alias in content:
        content = content.replace(old_alias, new_alias, 1)

    # Remove the previous per-channel manual clock offsets. They double-shifted
    # channels whose API timestamps were already UTC.
    content = re.sub(
        r'\n\s*"clock_offset_hours":\s*-?\d+,\s*',
        '\n',
        content,
    )

    # Replace any previous regional_stamp implementation with the normal MTS
    # timestamp parser. stamp() correctly interprets a trailing Z as UTC.
    start = content.find("def regional_stamp(")
    end = content.find("\ndef parse_xmltv_time", start)
    if start < 0 or end < 0:
        raise SystemExit("Could not locate regional_stamp() in importer")
    correct_function = '''def regional_stamp(value):
    """Preserve MTS ISO timezone semantics; a trailing Z is UTC."""
    return stamp(value)

'''
    content = content[:start] + correct_function + content[end + 1:]

    # Scope call changes to import_regionals only, leaving K1 untouched.
    regional_start = content.find("def import_regionals(root):")
    k1_start = content.find("\ndef supplement_k1(root):", regional_start)
    if regional_start < 0 or k1_start < 0:
        raise SystemExit("Could not locate import_regionals() boundaries")
    prefix = content[:regional_start]
    regional = content[regional_start:k1_start]
    suffix = content[k1_start:]
    regional = regional.replace(
        'regional_stamp(item["start"], target.get("clock_offset_hours", 0))',
        'regional_stamp(item["start"])',
    )
    regional = regional.replace(
        'regional_stamp(item["end"], target.get("clock_offset_hours", 0))',
        'regional_stamp(item["end"])',
    )
    content = prefix + regional + suffix

    if content != original:
        PATH.write_text(content, encoding="utf-8")
        print("Patched MTS regionals: standard UTC/ISO timestamps; removed manual offsets")
    else:
        print("MTS regional importer already uses standard UTC/ISO timestamps")


if __name__ == "__main__":
    main()
