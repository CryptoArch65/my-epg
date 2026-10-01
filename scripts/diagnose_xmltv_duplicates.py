#!/usr/bin/env python3
"""Report duplicate-looking XMLTV entries and playlist alias fan-out.

This is diagnostic only: it never modifies the guide.
"""

import csv
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ACTIVE_IDS = Path("config/active_playlist_tvg_ids.txt")


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(value.casefold().split())


def group_aliases(rows):
    by_target = defaultdict(list)
    for row in rows:
        by_target[row["guide_id"].strip()].append(
            (row["playlist_tvg_id"].strip(), row["display_name"].strip())
        )
    return by_target


def main(guide_path: Path, aliases_path: Path):
    with aliases_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    by_target = group_aliases(rows)
    multi = {k: v for k, v in by_target.items() if len(v) > 1}
    print(f"playlist_aliases.csv rows={len(rows)} canonical_targets={len(by_target)} targets_with_multiple_aliases={len(multi)}")

    active_ids = set()
    if ACTIVE_IDS.exists():
        active_ids = {
            line.strip()
            for line in ACTIVE_IDS.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        active_rows = [row for row in rows if row["playlist_tvg_id"].strip() in active_ids]
        active_by_target = group_aliases(active_rows)
        active_multi = {k: v for k, v in active_by_target.items() if len(v) > 1}
        print(
            f"ACTIVE-FILTER rows={len(active_rows)}/{len(rows)} "
            f"canonical_targets={len(active_by_target)} "
            f"targets_with_multiple_active_aliases={len(active_multi)}"
        )
        for target, aliases in sorted(active_multi.items(), key=lambda item: (-len(item[1]), item[0].casefold())):
            joined = " | ".join(f"{alias!r} => {name!r}" for alias, name in aliases)
            print(f"ACTIVE-FANOUT {target}: {len(aliases)} aliases :: {joined}")

    root = ET.parse(guide_path).getroot()
    alias_ids = {row["playlist_tvg_id"].strip() for row in rows}
    inactive_alias_ids = alias_ids - active_ids if active_ids else set()

    def duplicate_count(skip_ids=None):
        skip_ids = skip_ids or set()
        groups = defaultdict(list)
        kept = 0
        for channel in root.findall("channel"):
            cid = channel.get("id") or ""
            if cid in skip_ids:
                continue
            kept += 1
            names = [n.text.strip() for n in channel.findall("display-name") if n.text and n.text.strip()]
            if not names:
                continue
            groups[norm(names[0])].append((cid, names[0]))
        dups = [v for v in groups.values() if len(v) > 1]
        return kept, dups

    channels, duplicate_groups = duplicate_count()
    print(f"guide channels={channels} duplicate_primary_display_groups={len(duplicate_groups)}")

    if active_ids:
        filtered_channels, filtered_dups = duplicate_count(inactive_alias_ids)
        print(
            f"SIMULATED-ACTIVE-ONLY guide_channels={filtered_channels} "
            f"duplicate_primary_display_groups={len(filtered_dups)} "
            f"removed_inactive_alias_channels={channels-filtered_channels}"
        )
        for entries in sorted(filtered_dups, key=lambda v: (-len(v), v[0][1].casefold())):
            print("ACTIVE-DISPLAY-DUP " + " | ".join(f"{cid!r}:{name!r}" for cid, name in entries))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: diagnose_xmltv_duplicates.py guide.xml config/playlist_aliases.csv")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
