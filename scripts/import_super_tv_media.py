#!/usr/bin/env python3
"""Import |BIH| SUPER TV MEDIA EPG and logo from supertelevizija.com/guide/."""

import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from lxml import html

SOURCE = "https://supertelevizija.com/guide/"
LOGO = "https://supertelevizija.com/wp-content/uploads/2023/09/cropped-cropped-SUPER-TV-LOGO-OPERATERI-1-285x95.png"
CID = "supermediatelevizija.ba"
DISPLAY = "|BIH| SUPER TV MEDIA"
TZ = ZoneInfo("Europe/Sarajevo")
TIME_RE = re.compile(r"^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$")


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
    tokens = [" ".join(t.split()) for t in doc.xpath("//body//text()")]
    tokens = [t for t in tokens if t]
    today = datetime.now(TZ).date()
    events = []

    for i, token in enumerate(tokens):
        m = TIME_RE.fullmatch(token)
        if not m:
            continue
        title = ""
        for candidate in tokens[i + 1 : i + 8]:
            if TIME_RE.fullmatch(candidate):
                break
            low = candidate.casefold()
            if low in {
                "pregled programa", "all events", "super tv", "main menu",
                "search", "gledaj uzivo", "pocetna", "super vijesti",
                "zabava", "sport", "vjerski program", "marketing",
            }:
                continue
            title = candidate.strip()
            break
        if not title:
            continue
        start = datetime.strptime(f"{today} {m.group(1)}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        stop = datetime.strptime(f"{today} {m.group(2)}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        if stop <= start:
            stop = stop.replace(day=stop.day)  # keep explicit before rollover adjustment
            from datetime import timedelta
            stop += timedelta(days=1)
        events.append((start, stop, title))

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
    events = parse_events(fetch())
    if len(events) < 3:
        raise SystemExit(f"SUPER TV source returned only {len(events)} usable programmes")

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
    print(f"SUPER TV MEDIA: programmes={len(events)}, logo={LOGO}, source={SOURCE}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_super_tv_media.py guide.xml")
    main(sys.argv[1])
