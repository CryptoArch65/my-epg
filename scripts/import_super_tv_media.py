#!/usr/bin/env python3
"""Import |BIH| SUPER TV MEDIA EPG and logo from supertelevizija.com/guide/."""

import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from lxml import html

SOURCE = "https://supertelevizija.com/guide/"
LOGO = "https://supertelevizija.com/wp-content/uploads/2023/09/cropped-cropped-SUPER-TV-LOGO-OPERATERI-1-285x95.png"
CID = "supermediatelevizija.ba"
DISPLAY = "|BIH| SUPER TV MEDIA"
TZ = ZoneInfo("Europe/Sarajevo")
TIME_RE = re.compile(r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})")


def fetch():
    req = Request(
        SOURCE,
        headers={
            "User-Agent": "Mozilla/5.0 (EPG guide)",
            "Accept-Language": "bs-BA,bs;q=0.9,hr;q=0.8,sr;q=0.7,en;q=0.5",
        },
    )
    with urlopen(req, timeout=40) as r:
        return r.read(3_000_000)


def clean_title(segment):
    value = " ".join(segment.replace("\xa0", " ").split()).strip()
    if not value:
        return ""
    # The page repeats the schedule and then continues into footer/navigation text.
    # Keep only the programme title that immediately follows each time range.
    for marker in (
        "Pregled programa",
        "All Events",
        "Main Menu",
        "Gledaj uzivo",
        "Copyright ©",
        "Copyright",
    ):
        pos = value.find(marker)
        if pos > 0:
            value = value[:pos].strip()
        elif pos == 0:
            value = ""
    return value.strip(" -|–—")


def parse_events(raw):
    doc = html.fromstring(raw)
    # Parse the complete rendered text instead of individual text nodes because
    # Super TV splits the start/end clock across nested HTML elements.
    body = doc.text_content().replace("\xa0", " ")
    matches = list(TIME_RE.finditer(body))
    today = datetime.now(TZ).date()
    events = []

    for i, match in enumerate(matches):
        end_of_segment = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        title = clean_title(body[match.end() : end_of_segment])
        if not title:
            continue

        start = datetime.strptime(
            f"{today} {match.group(1)}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=TZ)
        stop = datetime.strptime(
            f"{today} {match.group(2)}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=TZ)
        if stop <= start:
            stop += timedelta(days=1)
        events.append((start, stop, title))

    # The website currently renders the programme block twice; de-duplicate it.
    unique = {}
    for start, stop, title in events:
        unique[(start, stop, title)] = (start, stop, title)
    return sorted(unique.values(), key=lambda row: row[0])


def ensure_channel(root):
    ch = next((c for c in root.findall("channel") if c.get("id") == CID), None)
    if ch is None:
        ch = ET.Element("channel", {"id": CID})
        root.insert(len(root.findall("channel")), ch)
    names = [(n.text or "").strip() for n in ch.findall("display-name")]
    if DISPLAY not in names:
        ET.SubElement(ch, "display-name", {"lang": "bs"}).text = DISPLAY
    for icon in list(ch.findall("icon")):
        ch.remove(icon)
    ET.SubElement(ch, "icon", {"src": LOGO})
    return ch


def main(path):
    raw = fetch()
    events = parse_events(raw)
    if len(events) < 3:
        text_sample = " ".join(html.fromstring(raw).text_content().split())[:700]
        raise SystemExit(
            f"SUPER TV source returned only {len(events)} usable programmes; "
            f"page sample={text_sample!r}"
        )

    tree = ET.parse(path)
    root = tree.getroot()
    ensure_channel(root)

    for p in list(root.findall("programme")):
        if p.get("channel") == CID:
            root.remove(p)

    for start, stop, title in events:
        p = ET.SubElement(
            root,
            "programme",
            {
                "channel": CID,
                "start": start.strftime("%Y%m%d%H%M%S %z"),
                "stop": stop.strftime("%Y%m%d%H%M%S %z"),
            },
        )
        ET.SubElement(p, "title", {"lang": "bs"}).text = title

    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(
        f"SUPER TV MEDIA: programmes={len(events)}, "
        f"first={events[0][0].isoformat()} {events[0][2]!r}, "
        f"last={events[-1][0].isoformat()} {events[-1][2]!r}, "
        f"logo={LOGO}, source={SOURCE}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_super_tv_media.py guide.xml")
    main(sys.argv[1])
