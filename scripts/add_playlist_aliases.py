#!/usr/bin/env python3
"""Expose the playlist's existing tvg-id values as XMLTV channel aliases."""

import collections
import copy
import csv
import sys
import xml.etree.ElementTree as ET


def read_aliases(path):
    with open(path, newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["playlist_tvg_id", "guide_id", "display_name"]:
            raise ValueError("Unexpected alias CSV header")
        aliases = {}
        for row in reader:
            alias, target, name = (row[key].strip() for key in reader.fieldnames)
            if not alias or not target or not name or alias in aliases:
                raise ValueError(f"Invalid or duplicate playlist alias: {alias!r}")
            aliases[alias] = (target, name)
    return aliases


def main(guide_path, alias_path):
    aliases = read_aliases(alias_path)
    tree = ET.parse(guide_path)
    root = tree.getroot()
    if root.tag != "tv":
        raise ValueError("Expected XMLTV <tv> root")

    channels = {element.get("id"): element for element in root.findall("channel")}
    if len(channels) != len(root.findall("channel")):
        raise ValueError("Duplicate source channel ID")
    for alias, (target, _) in aliases.items():
        if alias in channels or target not in channels:
            raise ValueError(f"Alias {alias!r} conflicts with a channel or has missing target {target!r}")

    aliases_by_target = collections.defaultdict(list)
    for alias, (target, name) in aliases.items():
        aliases_by_target[target].append(alias)
        channel = copy.deepcopy(channels[target])
        channel.set("id", alias)
        for display_name in channel.findall("display-name"):
            channel.remove(display_name)
        channel.insert(0, ET.Element("display-name"))
        channel[0].text = name
        # XMLTV channel entries must precede programme entries.
        root.insert(len(channels), channel)

    original_programmes = list(root.findall("programme"))
    for programme in original_programmes:
        for alias in aliases_by_target.get(programme.get("channel"), ()):
            duplicate = copy.deepcopy(programme)
            duplicate.set("channel", alias)
            root.append(duplicate)

    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(f"Added {len(aliases)} playlist ID aliases to the XMLTV guide")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: add_playlist_aliases.py guide.xml config/playlist_aliases.csv")
    main(sys.argv[1], sys.argv[2])
