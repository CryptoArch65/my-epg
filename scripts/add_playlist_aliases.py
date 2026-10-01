#!/usr/bin/env python3
"""Expose only active playlist tvg-id values as XMLTV channel aliases."""

import collections
import copy
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_ACTIVE_IDS = Path("config/active_playlist_tvg_ids.txt")


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


def read_alias_logos(path):
    with open(path, newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["playlist_tvg_id", "logo_url"]:
            raise ValueError("Unexpected playlist logo CSV header")
        logos = {}
        for row in reader:
            alias, url = row["playlist_tvg_id"].strip(), row["logo_url"].strip()
            parsed = urlparse(url)
            if not alias or alias in logos or parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(f"Invalid playlist logo for {alias!r}")
            logos[alias] = url
    return logos


def read_active_ids(path):
    active = set()
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if value and not value.startswith("#"):
            active.add(value)
    return active


def main(guide_path, alias_path, logos_path=None, active_ids_path=None):
    all_aliases = read_aliases(alias_path)
    logos = read_alias_logos(logos_path) if logos_path else {}
    if set(logos) - set(all_aliases):
        raise ValueError("Playlist logo references a missing alias")

    if active_ids_path is None and DEFAULT_ACTIVE_IDS.exists():
        active_ids_path = DEFAULT_ACTIVE_IDS

    aliases = all_aliases
    if active_ids_path:
        active_ids = read_active_ids(active_ids_path)
        aliases = {
            alias: target
            for alias, target in all_aliases.items()
            if alias in active_ids
        }
        logos = {alias: url for alias, url in logos.items() if alias in aliases}
        skipped = sorted(set(all_aliases) - set(aliases))
        print(
            f"Playlist alias activity filter: active={len(aliases)}/{len(all_aliases)} "
            f"skipped_inactive={len(skipped)}"
        )
        if skipped:
            print("Inactive aliases not cloned: " + ", ".join(skipped))

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
        if alias in logos:
            for icon in channel.findall("icon"):
                channel.remove(icon)
            channel.append(ET.Element("icon", {"src": logos[alias]}))
        # XMLTV channel entries must precede programme entries.
        root.insert(len(channels), channel)

    original_programmes = list(root.findall("programme"))
    for programme in original_programmes:
        for alias in aliases_by_target.get(programme.get("channel"), ()):
            duplicate = copy.deepcopy(programme)
            duplicate.set("channel", alias)
            root.append(duplicate)

    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(f"Added {len(aliases)} active playlist ID aliases to the XMLTV guide")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4, 5):
        raise SystemExit(
            "Usage: add_playlist_aliases.py guide.xml config/playlist_aliases.csv "
            "[config/playlist-alias-logos.csv] [config/active_playlist_tvg_ids.txt]"
        )
    main(*sys.argv[1:])
