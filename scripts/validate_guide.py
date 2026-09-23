#!/usr/bin/env python3
"""Prevent a partial or broken grab from replacing the published XMLTV guide."""

import collections
import math
import sys
import xml.etree.ElementTree as ET

# Live PR grab on 2026-09-23 returned zero programmes for all Serbian Arena
# channels from this site. Keep their real IDs in the guide and report the
# outage, while allowing the other five providers to update normally.
KNOWN_EMPTY_SITES = {"tvarenasport.com"}


def main(config_path, guide_path):
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
            if channel_id not in expected:
                raise ValueError(f"Unexpected guide channel: {channel_id}")
            if channel_id in actual:
                raise ValueError(f"Duplicate guide channel: {channel_id}")
            actual.add(channel_id)
            element.clear()
        elif element.tag == "programme":
            channel_id = element.get("channel")
            if channel_id not in expected:
                raise ValueError(f"Programme uses unknown channel: {channel_id}")
            if not element.get("start") or element.find("title") is None:
                raise ValueError(f"Incomplete programme on channel: {channel_id}")
            programmes_by_channel[channel_id] += 1
            element.clear()

    active = set(programmes_by_channel)
    if not active.issubset(actual):
        raise ValueError("Guide has programmes without a channel entry")

    minimum_active = math.ceil(len(expected) / 2)
    if len(active) < minimum_active or sum(programmes_by_channel.values()) < 500:
        raise ValueError(
            f"Too little programme data: {len(active)}/{len(expected)} channels, "
            f"{sum(programmes_by_channel.values())} programmes"
        )

    missing_sites = set(expected.values()) - {expected[channel_id] for channel_id in active}
    unexpected_missing = missing_sites - KNOWN_EMPTY_SITES
    if unexpected_missing:
        raise ValueError("No programmes for source(s): " + ", ".join(sorted(unexpected_missing)))
    if missing_sites:
        print("WARNING: No programmes for source(s): " + ", ".join(sorted(missing_sites)))

    print(
        f"Guide validated: {len(actual)} channels, {len(active)} with programmes, "
        f"{sum(programmes_by_channel.values())} programmes across {len(set(expected.values()))} sites"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: validate_guide.py config/channels.xml guide.new.xml")
    main(sys.argv[1], sys.argv[2])
