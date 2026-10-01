#!/usr/bin/env python3
"""Permanently patch the Serbian MTS regional importer.

MTS regional timestamps are not consistent across all channels. First, their
ISO clock values carry a trailing ``Z`` even when the clock itself represents
Europe/Belgrade local time. A small subset is then still two hours late versus
broadcaster/live schedules. Keep that second correction channel-specific.
"""

from pathlib import Path

PATH = Path("scripts/import_mts_serbia_epg.py")

# Confirmed against broadcaster/current programme schedules. Channels not in
# this table keep the MTS local clock unchanged.
EXTRA_OFFSETS = {
    "TVKrusevac.rs": -2,
    "NewsmaxBalkans.rs": -2,
    "SOSKanalPlus.rs": -2,
    "PesterTV.rs": -2,
}


def add_target_offset(content, guide_id, hours):
    marker = f'        "guide_id": "{guide_id}",'
    start = content.find(marker)
    if start < 0:
        raise SystemExit(f"Regional target not found: {guide_id}")
    end = content.find("    },", start)
    if end < 0:
        raise SystemExit(f"Regional target block is incomplete: {guide_id}")
    block = content[start:end]
    wanted = f'        "clock_offset_hours": {hours},'
    if wanted in block:
        return content, False
    if '"clock_offset_hours":' in block:
        import re
        block = re.sub(
            r'^\s*"clock_offset_hours":\s*-?\d+,\s*$',
            wanted,
            block,
            flags=re.MULTILINE,
        )
        return content[:start] + block + content[end:], True
    block = block + "\n" + wanted
    return content[:start] + block + content[end:], True


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

    old_function = '''def regional_stamp(value):
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
    new_function = '''def regional_stamp(value, offset_hours=0):
    """Interpret an MTS regional clock as Serbia local time plus a safe override.

    MTS appends ``Z`` to regional programme times even when the visible clock is
    already Europe/Belgrade local time. A few channels are additionally two
    hours late in MTS itself; ``offset_hours`` corrects only those channels.
    """
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            local = __import__("datetime").datetime.fromisoformat(text[:-1])
            if local.tzinfo is not None:
                local = local.replace(tzinfo=None)
            local = local.replace(tzinfo=ZONE)
            if offset_hours:
                local = local + timedelta(hours=offset_hours)
            return local.strftime("%Y%m%d%H%M%S %z")
    parsed = parse_xmltv_time(stamp(value)).astimezone(ZONE)
    if offset_hours:
        parsed = parsed + timedelta(hours=offset_hours)
    return parsed.strftime("%Y%m%d%H%M%S %z")
'''

    if new_function not in content:
        if old_function in content:
            content = content.replace(old_function, new_function, 1)
            changed = True
        elif "def regional_stamp(value, offset_hours=0):" not in content:
            raise SystemExit("regional_stamp() structure changed unexpectedly")

    for guide_id, hours in EXTRA_OFFSETS.items():
        content, did_change = add_target_offset(content, guide_id, hours)
        changed = changed or did_change

    # Scope timestamp call changes strictly to import_regionals(). K1 and all
    # other MTS importers keep their existing timestamp behavior.
    regional_start = content.find("def import_regionals(root):")
    k1_start = content.find("\ndef supplement_k1(root):", regional_start)
    if regional_start < 0 or k1_start < 0:
        raise SystemExit("Could not locate import_regionals() boundaries")

    prefix = content[:regional_start]
    regional = content[regional_start:k1_start]
    suffix = content[k1_start:]

    old_start = 'start = regional_stamp(item["start"])'
    old_stop = 'stop = regional_stamp(item["end"])'
    new_start = 'start = regional_stamp(item["start"], target.get("clock_offset_hours", 0))'
    new_stop = 'stop = regional_stamp(item["end"], target.get("clock_offset_hours", 0))'

    if new_start not in regional:
        if regional.count(old_start) != 1:
            raise SystemExit("Regional start timestamp statement changed unexpectedly")
        regional = regional.replace(old_start, new_start, 1)
        changed = True
    if new_stop not in regional:
        if regional.count(old_stop) != 1:
            raise SystemExit("Regional stop timestamp statement changed unexpectedly")
        regional = regional.replace(old_stop, new_stop, 1)
        changed = True

    content = prefix + regional + suffix

    if changed:
        PATH.write_text(content, encoding="utf-8")
        print(
            "Patched MTS regionals: Serbia-local clock; -2h overrides for "
            + ", ".join(EXTRA_OFFSETS)
        )
    else:
        print("MTS regional importer already has channel-specific clock fixes")


if __name__ == "__main__":
    main()
