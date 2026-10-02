#!/usr/bin/env python3
"""Import Mreža Zagreb schedule from Gledaj.hr into an XMLTV guide."""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

CHANNEL_ID = "MrezaZG.hr"
CHANNEL_NAME = "|HR| MREZA ZAGREB"
GLEDAJ_CHANNEL = 299
TZ = ZoneInfo("Europe/Zagreb")
RTL_ID = "RTL.hr"
RTL_DISPLAY_ALIASES = ("|HR| RTL", "|HR| RTL HD")

MONTHS = {
    "sij": 1, "siječ": 1, "sijecn": 1,
    "velj": 2,
    "ožu": 3, "ozu": 3,
    "tra": 4,
    "svi": 5,
    "lip": 6,
    "srp": 7,
    "kol": 8,
    "ruj": 9,
    "lis": 10,
    "stu": 11,
    "pro": 12,
}

DATE_RE = re.compile(r"(?i)(\d{1,2})\.\s*([A-Za-zČĆŽŠĐčćžšđ]+)[a-zčćžšđ.]*\s*(\d{4})?\.?$")
PROGRAM_RE = re.compile(r"^(\d{2})(\d{2})\s+(.+\S)$")


def month_number(word: str) -> int | None:
    value = word.lower().replace("č", "c").replace("ć", "c").replace("ž", "z").replace("š", "s").replace("đ", "d")
    for prefix, number in MONTHS.items():
        clean = prefix.replace("č", "c").replace("ć", "c").replace("ž", "z").replace("š", "s").replace("đ", "d")
        if value.startswith(clean):
            return number
    return None


def local_noon_ms(day: date) -> int:
    dt = datetime(day.year, day.month, day.day, 12, 0, tzinfo=TZ)
    return int(dt.timestamp() * 1000)


def fetch_text(day: date) -> str:
    url = f"https://player.gledaj.hr/tv/epg/{GLEDAJ_CHANNEL}/time/{local_noon_ms(day)}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="hr-HR")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_timeout(4000)
            text = page.locator("body").inner_text(timeout=15000)
        finally:
            browser.close()
    print(f"Gledaj fetch: {url} chars={len(text)}")
    return text


def parse_schedule(text: str, default_year: int) -> list[tuple[datetime, str]]:
    current_day: date | None = None
    rows: list[tuple[datetime, str]] = []

    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue

        dm = DATE_RE.search(line)
        if dm:
            month = month_number(dm.group(2))
            if month:
                year = int(dm.group(3) or default_year)
                try:
                    current_day = date(year, month, int(dm.group(1)))
                except ValueError:
                    pass
            continue

        pm = PROGRAM_RE.match(line)
        if not pm or current_day is None:
            continue

        hour, minute = int(pm.group(1)), int(pm.group(2))
        if hour > 23 or minute > 59:
            continue
        title = pm.group(3).strip()
        if not title or title.lower() in {"nema podataka", "no information"}:
            continue
        start = datetime(current_day.year, current_day.month, current_day.day, hour, minute, tzinfo=TZ)
        rows.append((start, title))

    return sorted(set(rows), key=lambda row: row[0])


def xmltv_time(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S %z")


def add_rtl_display_aliases(root: ET.Element) -> None:
    channel = next((node for node in root.findall("channel") if node.get("id") == RTL_ID), None)
    if channel is None:
        print("RTL alias warning: RTL.hr channel not found")
        return

    existing = {(node.text or "").strip() for node in channel.findall("display-name")}
    added = []
    for alias in RTL_DISPLAY_ALIASES:
        if alias not in existing:
            ET.SubElement(channel, "display-name", {"lang": "hr"}).text = alias
            added.append(alias)
    print(f"RTL.hr display aliases added: {added or 'none (already present)'}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_gledaj_mreza_zagreb.py guide.xml")

    guide_path = Path(sys.argv[1])
    tree = ET.parse(guide_path)
    root = tree.getroot()

    add_rtl_display_aliases(root)

    today = datetime.now(TZ).date()
    all_rows: list[tuple[datetime, str]] = []
    for offset in (0, 1):
        text = fetch_text(today + timedelta(days=offset))
        all_rows.extend(parse_schedule(text, (today + timedelta(days=offset)).year))

    rows = sorted(set(all_rows), key=lambda row: row[0])
    if not rows:
        raise SystemExit("Gledaj.hr returned no parsable Mreza Zagreb programmes")

    for node in list(root.findall("channel")):
        if node.get("id") == CHANNEL_ID:
            root.remove(node)
    for node in list(root.findall("programme")):
        if node.get("channel") == CHANNEL_ID:
            root.remove(node)

    channel = ET.Element("channel", {"id": CHANNEL_ID})
    ET.SubElement(channel, "display-name", {"lang": "hr"}).text = CHANNEL_NAME
    root.insert(0, channel)

    now = datetime.now(TZ)
    useful = [(start, title) for start, title in rows if start >= now - timedelta(days=1) and start <= now + timedelta(days=4)]
    if not useful:
        useful = rows

    added = 0
    for index, (start, title) in enumerate(useful):
        stop = useful[index + 1][0] if index + 1 < len(useful) else start + timedelta(hours=1)
        if stop <= start:
            continue
        programme = ET.Element("programme", {
            "start": xmltv_time(start),
            "stop": xmltv_time(stop),
            "channel": CHANNEL_ID,
        })
        ET.SubElement(programme, "title", {"lang": "hr"}).text = title
        root.append(programme)
        added += 1

    if added < 3:
        raise SystemExit(f"Only {added} Mreza Zagreb programmes parsed; refusing to publish")

    ET.indent(tree, space="  ")
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(f"Mreza Zagreb: imported {added} programmes from Gledaj.hr channel {GLEDAJ_CHANNEL}")
    print(f"First: {useful[0][0].isoformat()} {useful[0][1]}")
    print(f"Last:  {useful[-1][0].isoformat()} {useful[-1][1]}")


if __name__ == "__main__":
    main()
