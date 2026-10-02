#!/usr/bin/env python3
"""Import Mreža Zagreb schedule from Gledaj.hr into an XMLTV guide."""

from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

CHANNEL_ID = "MrezaZG.hr"
CHANNEL_NAME = "|HR| MREZA ZAGREB"
GLEDAJ_CHANNEL = 299
TZ = ZoneInfo("Europe/Zagreb")
RTL_ID = "RTL.hr"
RTL_DISPLAY_ALIASES = ("|HR| RTL", "|HR| RTL HD")


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


def fetch_entries() -> list[dict]:
    """Open the public Gledaj page and collect JSON EPG responses for channel 299."""
    now = datetime.now(TZ)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    millis = int(midnight.timestamp() * 1000)
    url = f"https://player.gledaj.hr/tv/epg/{GLEDAJ_CHANNEL}/time/{millis}"

    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="hr-HR")

        def on_response(response):
            if "/client/tv/getEpg" not in response.url:
                return
            try:
                data = response.json()
            except Exception as exc:
                print(f"Gledaj response parse warning: {exc!r}")
                return
            entries = data.get("entries") or []
            matching = [entry for entry in entries if int(entry.get("channelId", -1)) == GLEDAJ_CHANNEL]
            if matching:
                print(f"Gledaj API response: {len(entries)} total entries, {len(matching)} for channel {GLEDAJ_CHANNEL}")
                captured.extend(matching)

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # The channel-specific multi-day EPG request is issued shortly after page load.
        # Wait until it arrives or until the conservative timeout is reached.
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if len(captured) >= 20:
                break
            page.wait_for_timeout(500)

        browser.close()

    # Deduplicate entries that may appear in both the short live window and
    # the wider channel-specific response.
    deduped: dict[tuple[str, str, str], dict] = {}
    for entry in captured:
        start = str(entry.get("startTimestamp") or "")
        stop = str(entry.get("endTimestamp") or "")
        title = str(entry.get("name") or entry.get("nameSingleLine") or "").strip()
        if not start or not stop or not title:
            continue
        deduped[(start, stop, title)] = entry

    rows = sorted(deduped.values(), key=lambda item: int(item["startTimestamp"]))
    print(f"Gledaj channel {GLEDAJ_CHANNEL}: {len(rows)} unique programmes captured")
    return rows


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_gledaj_mreza_zagreb.py guide.xml")

    guide_path = Path(sys.argv[1])
    tree = ET.parse(guide_path)
    root = tree.getroot()

    entries = fetch_entries()
    if len(entries) < 3:
        raise SystemExit(f"Only {len(entries)} Mreza Zagreb programmes captured; refusing to publish")

    add_rtl_display_aliases(root)

    for node in list(root.findall("channel")):
        if node.get("id") == CHANNEL_ID:
            root.remove(node)
    for node in list(root.findall("programme")):
        if node.get("channel") == CHANNEL_ID:
            root.remove(node)

    channel = ET.Element("channel", {"id": CHANNEL_ID})
    ET.SubElement(channel, "display-name", {"lang": "hr"}).text = CHANNEL_NAME
    ET.SubElement(channel, "display-name", {"lang": "hr"}).text = "Mreža ZG"
    root.insert(0, channel)

    added = 0
    for entry in entries:
        start = datetime.fromtimestamp(int(entry["startTimestamp"]) / 1000, TZ)
        stop = datetime.fromtimestamp(int(entry["endTimestamp"]) / 1000, TZ)
        if stop <= start:
            continue

        title = str(entry.get("name") or entry.get("nameSingleLine") or "").strip()
        programme = ET.Element(
            "programme",
            {
                "start": xmltv_time(start),
                "stop": xmltv_time(stop),
                "channel": CHANNEL_ID,
            },
        )
        ET.SubElement(programme, "title", {"lang": "hr"}).text = title

        show = entry.get("show") or {}
        description = str(show.get("longDescription") or entry.get("description") or "").strip()
        if description:
            ET.SubElement(programme, "desc", {"lang": "hr"}).text = description

        images = entry.get("images") or []
        if images and images[0].get("url"):
            image_url = str(images[0]["url"])
            if image_url.startswith("/"):
                image_url = "https://player.gledaj.hr" + image_url
            ET.SubElement(programme, "icon", {"src": image_url})

        root.append(programme)
        added += 1

    if added < 3:
        raise SystemExit(f"Only {added} valid Mreza Zagreb programmes generated; refusing to publish")

    ET.indent(tree, space="  ")
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)

    first = entries[0]
    last = entries[-1]
    print(f"Mreza Zagreb: imported {added} programmes from Gledaj.hr channel {GLEDAJ_CHANNEL}")
    print(
        "First:",
        datetime.fromtimestamp(int(first["startTimestamp"]) / 1000, TZ).isoformat(),
        first.get("name"),
    )
    print(
        "Last:",
        datetime.fromtimestamp(int(last["endTimestamp"]) / 1000, TZ).isoformat(),
        last.get("name"),
    )


if __name__ == "__main__":
    main()
