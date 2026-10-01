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


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(value.casefold().split())


def main(guide_path: Path, aliases_path: Path):
    rows = []
    with aliases_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    by_target = defaultdict(list)
    for row in rows:
        by_target[row["guide_id"].strip()].append(
            (row["playlist_tvg_id"].strip(), row["display_name"].strip())
        )

    multi = {k: v for k, v in by_target.items() if len(v) > 1}
    print(f"playlist_aliases.csv rows={len(rows)} canonical_targets={len(by_target)} targets_with_multiple_aliases={len(multi)}")
    for target, aliases in sorted(multi.items(), key=lambda item: (-len(item[1]), item[0].casefold())):
        joined = " | ".join(f"{alias!r} => {name!r}" for alias, name in aliases)
        print(f"ALIAS-FANOUT {target}: {len(aliases)} aliases :: {joined}")

    root = ET.parse(guide_path).getroot()
    groups = defaultdict(list)
    for channel in root.findall("channel"):
        cid = channel.get("id") or ""
        names = [n.text.strip() for n in channel.findall("display-name") if n.text and n.text.strip()]
        if not names:
            continue
        groups[norm(names[0])].append((cid, names[0]))

    duplicate_groups = [v for v in groups.values() if len(v) > 1]
    print(f"guide channels={len(root.findall('channel'))} duplicate_primary_display_groups={len(duplicate_groups)}")
    for entries in sorted(duplicate_groups, key=lambda v: (-len(v), v[0][1].casefold())):
        print("DISPLAY-DUP " + " | ".join(f"{cid!r}:{name!r}" for cid, name in entries))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: diagnose_xmltv_duplicates.py guide.xml config/playlist_aliases.csv")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
