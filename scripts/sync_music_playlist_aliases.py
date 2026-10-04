#!/usr/bin/env python3
"""Clone canonical music EPG channels to the exact tvg-id values used by the playlist.

Unlike add_playlist_aliases.py this helper is intentionally idempotent because it
runs after the music-extra merge against an already-published guide. Existing
music aliases are replaced from their canonical target on every run.
"""

import copy
import csv
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


def read_aliases(path: Path):
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        expected = ["playlist_tvg_id", "guide_id", "display_name"]
        if reader.fieldnames != expected:
            raise ValueError(f"Unexpected CSV header: {reader.fieldnames!r}")
        rows = []
        seen = set()
        for row in reader:
            alias = row["playlist_tvg_id"].strip()
            target = row["guide_id"].strip()
            name = row["display_name"].strip()
            if not alias or not target or not name or alias in seen:
                raise ValueError(f"Invalid/duplicate music alias: {alias!r}")
            seen.add(alias)
            rows.append((alias, target, name))
        return rows


def main(guide_path: Path, aliases_path: Path) -> None:
    aliases = read_aliases(aliases_path)
    tree = ET.parse(guide_path)
    root = tree.getroot()
    if root.tag != "tv":
        raise ValueError("Expected XMLTV <tv> root")

    # Snapshot canonical channels/programmes before removing any stale aliases.
    channels = {c.get("id"): c for c in root.findall("channel") if c.get("id")}
    programmes_by_channel = defaultdict(list)
    for programme in root.findall("programme"):
        programmes_by_channel[programme.get("channel")].append(programme)

    missing = sorted({target for _, target, _ in aliases if target not in channels})
    if missing:
        raise ValueError("Missing canonical music EPG targets: " + ", ".join(missing))

    alias_ids = {alias for alias, _, _ in aliases}
    for channel in list(root.findall("channel")):
        if channel.get("id") in alias_ids:
            root.remove(channel)
    for programme in list(root.findall("programme")):
        if programme.get("channel") in alias_ids:
            root.remove(programme)

    insert_at = len(root.findall("channel"))
    counts = {}
    for alias, target, display_name in aliases:
        channel = copy.deepcopy(channels[target])
        channel.set("id", alias)
        for node in list(channel.findall("display-name")):
            channel.remove(node)
        name = ET.Element("display-name")
        name.text = display_name
        channel.insert(0, name)
        root.insert(insert_at, channel)
        insert_at += 1

        count = 0
        for programme in programmes_by_channel.get(target, []):
            clone = copy.deepcopy(programme)
            clone.set("channel", alias)
            root.append(clone)
            count += 1
        counts[alias] = count

    ET.indent(tree, space="  ")
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    for alias, target, _ in aliases:
        print(f"music alias {alias} -> {target}: {counts[alias]} programmes")
    print(f"Synced {len(aliases)} music playlist aliases")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: sync_music_playlist_aliases.py guide.xml aliases.csv")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
