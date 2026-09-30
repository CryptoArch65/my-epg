#!/usr/bin/env python3
"""Add Croatia playlist tvg-id aliases, replacing logo-only placeholders when needed."""

import collections
import copy
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def read_aliases(path):
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["playlist_tvg_id", "guide_id", "display_name"]:
            raise ValueError("Unexpected Croatia alias CSV header")
        rows = list(reader)
    aliases = {}
    for row in rows:
        alias = row["playlist_tvg_id"].strip()
        target = row["guide_id"].strip()
        name = row["display_name"].strip()
        if not alias or not target or not name or alias in aliases:
            raise ValueError(f"Invalid or duplicate Croatia alias: {alias!r}")
        aliases[alias] = (target, name)
    return aliases


def main(guide_path, alias_path):
    aliases = read_aliases(alias_path)
    tree = ET.parse(guide_path)
    root = tree.getroot()
    if root.tag != "tv":
        raise ValueError("Expected XMLTV <tv> root")

    channels = {node.get("id"): node for node in root.findall("channel")}
    programmes_by_channel = collections.defaultdict(list)
    for programme in root.findall("programme"):
        programmes_by_channel[programme.get("channel")].append(programme)

    # Remove an earlier Croatia logo-only placeholder if it occupies an alias ID.
    preserved_icons = {}
    for alias in aliases:
        existing = channels.get(alias)
        if existing is None:
            continue
        if programmes_by_channel.get(alias):
            raise ValueError(f"Croatia alias {alias!r} already has programmes")
        icons = existing.findall("icon")
        if icons:
            preserved_icons[alias] = icons[0].get("src")
        root.remove(existing)
        del channels[alias]
        print(f"Removed logo-only Croatia placeholder {alias}")

    for alias, (target, _) in aliases.items():
        if target not in channels:
            raise ValueError(f"Croatia alias target is missing: {target!r}")

    # XMLTV channel elements must precede programme elements.
    first_programme_index = next((i for i, child in enumerate(root) if child.tag == "programme"), len(root))
    inserted = 0
    for alias, (target, name) in aliases.items():
        channel = copy.deepcopy(channels[target])
        channel.set("id", alias)
        for display_name in channel.findall("display-name"):
            channel.remove(display_name)
        display = ET.Element("display-name")
        display.text = name
        channel.insert(0, display)
        if alias in preserved_icons:
            for icon in channel.findall("icon"):
                channel.remove(icon)
            channel.append(ET.Element("icon", {"src": preserved_icons[alias]}))
        root.insert(first_programme_index + inserted, channel)
        inserted += 1

        for programme in programmes_by_channel.get(target, []):
            duplicate = copy.deepcopy(programme)
            duplicate.set("channel", alias)
            root.append(duplicate)

        print(f"Croatia EPG alias {alias} -> {target}: {len(programmes_by_channel.get(target, []))} programmes")

    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(f"Added {len(aliases)} Croatia playlist aliases")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: add_croatia_playlist_aliases.py guide.xml config/croatia-playlist-aliases.csv")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
