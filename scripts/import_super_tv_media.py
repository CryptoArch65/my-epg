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
TIME_RE = re.compile(r"^(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})$")


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


def parse_events(raw):
    doc = html.fromstring(raw)
    tokens = [" ".join(str(t).replace("\xa0", " ").split()) for t in doc.xpath("//body//text()")]
    tokens = [t for t in tokens if t]
    today = datetime.now(TZ).date()
    events = []

    # Super TV sometimes splits a range across nested text nodes. Build short
    # token windows until a complete HH:MM - HH:MM range is found, then use the
    # very next text token as the programme title. This avoids swallowing footer
    # navigation into the final programme name.
    i = 0
    while i < len(tokens):
        matched = None
        consumed = 0
        for width in (1, 2, 3, 4):
            if i + width > len(tokens):
                break
            candidate = " ".join(tokens[i : i + width])
            m = TIME_RE.fullmatch(candidate)
            if m:
                matched = m
                consumed = width
                break
        if not matched:
            i += 1
            continue

        title_index = i + consumed
        if title_index >= len(tokens):
            break
        title = tokens[title_index].strip()
        if not title or TIME_RE.fullmatch(title) or len(title) > 120:
            i += max(consumed, 1)
            continue

        start = datetime.strptime(
            f"{today} {matched.group(1)}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=TZ)
        stop = datetime.strptime(
            f"{today} {matched.group(2)}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=TZ)
        if stop <= start:
            stop += timedelta(days=1)
        events.append((start, stop, title))
        i = title_index + 1

    # The page currently renders the same programme block twice.
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
        f"titles={[row[2] for row in events]!r}, "
        f"logo={LOGO}, source={SOURCE}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_super_tv_media.py guide.xml")
    main(sys.argv[1])
