#!/usr/bin/env python3
"""Replace K1 EPG with the official weekly schedule from k1info.rs when available."""

import copy
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

URL = "https://www.k1info.rs/tv-program"
ZONE = ZoneInfo("Europe/Belgrade")
CHANNEL_ID = "K1.rs"
ALIASES = ("k1-tv", "k1_duplicate")
WEEKDAYS = (
    "ponedeljak", "utorak", "sreda", "četvrtak", "petak", "subota", "nedelja"
)
TIME_ROW = re.compile(r"^\s*(\d{1,2}[:.]\d{2})\s+(.+?)\s*$")


def fetch():
    request = Request(URL, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml",
    })
    with urlopen(request, timeout=35) as response:
        return response.read(3_000_001).decode("utf-8", errors="replace")


def normalized_text(tag):
    return " ".join(tag.stripped_strings).strip()


def rows_in(container):
    rows = []
    for tag in container.find_all(True):
        text = normalized_text(tag)
        match = TIME_ROW.match(text)
        if not match:
            continue
        # Keep the smallest useful element containing both clock and title.
        if any(TIME_ROW.match(normalized_text(child)) for child in tag.find_all(recursive=False)):
            continue
        clock = match.group(1).replace(".", ":")
        title = match.group(2).strip(" |–—-")
        if not title or len(title) > 180:
            continue
        row = (clock, title)
        if not rows or rows[-1] != row:
            rows.append(row)
    return rows


def schedule_panels(soup):
    # First try to resolve the weekday tab buttons to their panels.
    by_day = {}
    for day in WEEKDAYS:
        trigger = next(
            (tag for tag in soup.find_all(True)
             if normalized_text(tag).casefold() == day.casefold()),
            None,
        )
        if trigger is None:
            continue
        for attr in ("data-bs-target", "data-target", "href", "aria-controls"):
            value = trigger.get(attr)
            if not value:
                continue
            target_id = str(value).lstrip("#")
            panel = soup.find(id=target_id)
            if panel is not None:
                rows = rows_in(panel)
                if len(rows) >= 6:
                    by_day[day] = rows
                    break
    if len(by_day) == 7:
        return [by_day[day] for day in WEEKDAYS]

    # Common Bootstrap/custom tab panels.
    preferred = []
    seen = set()
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class") or []).casefold()
        ident = str(tag.get("id") or "").casefold()
        if not any(word in classes or word in ident for word in ("tab-pane", "program", "schedule")):
            continue
        rows = rows_in(tag)
        key = tuple(rows)
        if 6 <= len(rows) <= 30 and key not in seen:
            seen.add(key)
            preferred.append(rows)
    if len(preferred) >= 7:
        return preferred[:7]

    # Generic fallback: find seven distinct day-sized schedule containers.
    candidates = []
    seen = set()
    for tag in soup.find_all(True):
        rows = rows_in(tag)
        key = tuple(rows)
        if 8 <= len(rows) <= 30 and key not in seen:
            seen.add(key)
            candidates.append(rows)
    if len(candidates) >= 7:
        return candidates[:7]

    raise ValueError(f"Could not identify 7 K1 schedule panels (found {len(candidates)})")


def datetimes_for(day, rows):
    result = []
    current_date = day
    previous_minutes = None
    for clock, title in rows:
        hour, minute = (int(value) for value in clock.split(":"))
        minutes = hour * 60 + minute
        # Some K1 weekday blocks continue after midnight.
        if previous_minutes is not None and minutes + 8 * 60 < previous_minutes:
            current_date += timedelta(days=1)
        start = datetime.combine(current_date, datetime.min.time(), ZONE).replace(
            hour=hour, minute=minute
        )
        result.append((start, title))
        previous_minutes = minutes
    return result


def stamp(value):
    return value.strftime("%Y%m%d%H%M%S %z")


def ensure_alias(root, source_id, alias_id):
    channels = {node.get("id"): node for node in root.findall("channel")}
    source = channels[source_id]
    alias = channels.get(alias_id)
    if alias is None:
        alias = copy.deepcopy(source)
        alias.set("id", alias_id)
        root.insert(len(root.findall("channel")), alias)
    else:
        for child in list(alias):
            alias.remove(child)
        for child in source:
            alias.append(copy.deepcopy(child))

    for programme in list(root.findall("programme")):
        if programme.get("channel") == alias_id:
            root.remove(programme)
    for programme in root.findall("programme"):
        if programme.get("channel") == source_id:
            clone = copy.deepcopy(programme)
            clone.set("channel", alias_id)
            root.append(clone)


def main(path):
    tree = ET.parse(path)
    root = tree.getroot()
    channels = {node.get("id"): node for node in root.findall("channel")}
    if CHANNEL_ID not in channels:
        print(f"WARNING: {CHANNEL_ID} missing; official K1 import skipped")
        return

    try:
        soup = BeautifulSoup(fetch(), "html.parser")
        panels = schedule_panels(soup)
    except Exception as exc:
        print(f"WARNING: official K1 schedule unavailable; keeping existing EPG: {exc}")
        return

    today = datetime.now(ZONE).date()
    programmes = []
    for offset in (0, 1):
        day = today + timedelta(days=offset)
        rows = panels[day.weekday()]
        starts = datetimes_for(day, rows)
        next_day_rows = panels[(day.weekday() + 1) % 7]
        next_first = datetimes_for(day + timedelta(days=1), next_day_rows)[0][0]
        for index, (start, title) in enumerate(starts):
            if index + 1 < len(starts):
                stop = starts[index + 1][0]
            else:
                stop = next_first
                if stop <= start:
                    stop = start + timedelta(hours=1)
            if stop <= start:
                continue
            programmes.append((start, stop, title))

    if len(programmes) < 12:
        print(f"WARNING: official K1 parser returned only {len(programmes)} programmes; keeping existing EPG")
        return

    for programme in list(root.findall("programme")):
        if programme.get("channel") in (CHANNEL_ID, *ALIASES):
            root.remove(programme)

    for start, stop, title in programmes:
        node = ET.SubElement(
            root, "programme", channel=CHANNEL_ID,
            start=stamp(start), stop=stamp(stop)
        )
        ET.SubElement(node, "title", lang="sr").text = title

    for alias in ALIASES:
        ensure_alias(root, CHANNEL_ID, alias)

    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"K1 official: imported {len(programmes)} programmes for {today} and {today + timedelta(days=1)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_k1_official.py guide.xml")
    main(Path(sys.argv[1]))
