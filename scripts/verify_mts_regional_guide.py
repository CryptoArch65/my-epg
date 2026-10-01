#!/usr/bin/env python3
"""Report live/current XMLTV coverage for Serbian MTS regional channels."""

import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Belgrade")
TARGETS = (
    "TVIstok.rs",
    "TVLeskovac.rs",
    "JefimijaTV.rs",
    "TVKrusevac.rs",
    "NewsmaxBalkans.rs",
    "newsmaxbalkans.rs",
    "TVAS.rs",
    "TVBor.rs",
    "SOSKanalPlus.rs",
    "PesterTV.rs",
)


def parse_time(value):
    return datetime.strptime(value, "%Y%m%d%H%M%S %z").astimezone(ZONE)


def main(path):
    root = ET.parse(path).getroot()
    channels = {channel.get("id"): channel for channel in root.findall("channel")}
    programmes = root.findall("programme")
    counts = Counter(p.get("channel") for p in programmes)
    now = datetime.now(ZONE)
    print(f"Regional guide verification now={now.isoformat()}")

    for channel_id in TARGETS:
        channel = channels.get(channel_id)
        if channel is None:
            print(f"{channel_id}: MISSING")
            continue
        icon = channel.find("icon")
        current = []
        for programme in programmes:
            if programme.get("channel") != channel_id:
                continue
            try:
                start = parse_time(programme.get("start"))
                stop = parse_time(programme.get("stop"))
            except (TypeError, ValueError):
                continue
            if start <= now < stop:
                title = programme.findtext("title") or "(no title)"
                current.append((start, stop, title))
        current_text = "; ".join(
            f"{start:%H:%M}-{stop:%H:%M} {title}" for start, stop, title in current
        ) or "NONE"
        print(
            f"{channel_id}: programmes={counts[channel_id]} "
            f"logo={'yes' if icon is not None and icon.get('src') else 'no'} "
            f"current={current_text}"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify_mts_regional_guide.py guide.xml")
    main(sys.argv[1])
