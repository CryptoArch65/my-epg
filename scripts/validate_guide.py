#!/usr/bin/env python3
"""Prevent a partial or broken grab from replacing the published XMLTV guide."""

import collections
import csv
import math
import sys
import xml.etree.ElementTree as ET

# Live PR grab on 2026-09-23 returned zero programmes for all Serbian Arena
# channels from this site. Keep their real IDs in the guide and report the
# outage, while allowing the other five providers to update normally.
KNOWN_EMPTY_SITES = {"tvarenasport.com"}


def main(config_path, guide_path, alias_path=None):
    config = ET.parse(config_path).getroot()
    if config.tag != "channels":
        raise ValueError("Expected <channels> in channel configuration")

    expected = {}
    for channel in config.findall("channel"):
        site = channel.get("site")
        channel_id = channel.get("xmltv_id") or channel.get("site_id")
        if not site or not channel_id:
            raise ValueError("Configured channel has no site or ID")
        if channel_id in expected:
            raise ValueError(f"Duplicate output channel ID: {channel_id}")
        expected[channel_id] = site

    if not expected:
        raise ValueError("Channel configuration is empty")

    aliases = {}
    if alias_path:
        with open(alias_path, newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != ["playlist_tvg_id", "guide_id", "display_name"]:
                raise ValueError("Unexpected alias CSV header")
            for row in reader:
                alias, target = row["playlist_tvg_id"].strip(), row["guide_id"].strip()
                if not alias or alias in expected or alias in aliases or target not in expected:
                    raise ValueError(f"Invalid playlist alias: {alias!r} -> {target!r}")
                aliases[alias] = target

    allowed = set(expected) | set(aliases)

    actual = set()
    programmes_by_channel = collections.Counter()
    root_seen = False

    for event, element in ET.iterparse(guide_path, events=("start", "end")):
        if event == "start" and not root_seen:
            root_seen = True
            if element.tag != "tv":
                raise ValueError("Expected <tv> in generated XMLTV guide")

        if event != "end":
            continue

        if element.tag == "channel":
            channel_id = element.get("id")
            if channel_id not in allowed:
                raise ValueError(f"Unexpected guide channel: {channel_id}")
            if channel_id in actual:
                raise ValueError(f"Duplicate guide channel: {channel_id}")
            actual.add(channel_id)
            element.clear()
        elif element.tag == "programme":
            channel_id = element.get("channel")
            if channel_id not in allowed:
                raise ValueError(f"Programme uses unknown channel: {channel_id}")
            if not element.get("start") or element.find("title") is None:
                raise ValueError(f"Incomplete programme on channel: {channel_id}")
            programmes_by_channel[channel_id] += 1
            element.clear()

    active = set(programmes_by_channel)
    if not active.issubset(actual):
        raise ValueError("Guide has programmes without a channel entry")
    if actual != allowed:
        raise ValueError(f"Missing {len(allowed - actual)} configured guide channel(s)")
    for alias, target in aliases.items():
        if programmes_by_channel[alias] != programmes_by_channel[target]:
            raise ValueError(f"Alias programme count differs from its source: {alias!r}")

    active = active & set(expected)

    minimum_active = math.ceil(len(expected) / 2)
    source_programmes = sum(programmes_by_channel[channel_id] for channel_id in expected)
    if len(active) < minimum_active or source_programmes < 500:
        raise ValueError(
            f"Too little programme data: {len(active)}/{len(expected)} channels, "
            f"{source_programmes} programmes"
        )

    missing_sites = set(expected.values()) - {expected[channel_id] for channel_id in active}
    unexpected_missing = missing_sites - KNOWN_EMPTY_SITES
    if unexpected_missing:
        raise ValueError("No programmes for source(s): " + ", ".join(sorted(unexpected_missing)))
    if missing_sites:
        print("WARNING: No programmes for source(s): " + ", ".join(sorted(missing_sites)))

    print(
        f"Guide validated: {len(expected)} source channels, {len(aliases)} playlist aliases, "
        f"{len(active)} source channels with programmes, "
        f"{source_programmes} source programmes "
        f"across {len(set(expected.values()))} sites"
    )


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit("Usage: validate_guide.py config/channels.xml guide.new.xml [config/playlist_aliases.csv]")
    main(*sys.argv[1:])
