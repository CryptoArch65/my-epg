#!/usr/bin/env python3
"""Attach requested music-channel logos to XMLTV channels.

For normal websites and social profiles we first try the source page's OpenGraph
image. Social sites sometimes block automated requests, so every entry also has
a stable fallback URL; that prevents a broken logo from replacing a working one.
"""

from __future__ import annotations

import csv
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from lxml import html


def fetch(url: str) -> bytes:
    last = None
    for attempt in range(2):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.8,sr;q=0.7,hr;q=0.6",
            })
            with urlopen(req, timeout=30) as response:
                return response.read(3_000_000)
        except Exception as exc:
            last = exc
            if attempt == 0:
                time.sleep(1)
    raise last


def resolved_logo(source_page: str, fallback: str) -> tuple[str, str]:
    # Explicit direct images on the same official host are the most stable choice.
    source_host = urlparse(source_page).netloc.lower().removeprefix("www.")
    fallback_host = urlparse(fallback).netloc.lower().removeprefix("www.")
    if source_host and source_host == fallback_host and urlparse(fallback).path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".svg")):
        return fallback, "official-direct"

    try:
        doc = html.fromstring(fetch(source_page))
        candidates = []
        for meta in doc.xpath('//meta[@property="og:image"][@content] | //meta[@name="twitter:image"][@content] | //meta[@property="twitter:image"][@content]'):
            value = str(meta.get("content") or "").strip()
            if value:
                candidates.append(urljoin(source_page, value))
        # For ordinary sites, a logo image is often more appropriate than a page hero.
        if source_host not in {"youtube.com", "instagram.com", "facebook.com"}:
            for img in doc.xpath('//img[@src]'):
                value = str(img.get("src") or "").strip()
                label = " ".join((str(img.get("alt") or ""), str(img.get("title") or ""), value)).casefold()
                if value and "logo" in label:
                    candidates.insert(0, urljoin(source_page, value))
        for candidate in candidates:
            if candidate.startswith("https://"):
                return candidate, "source-page"
    except Exception as exc:
        print(f"WARNING logo source {source_page} unavailable: {exc!r}")

    return fallback, "stable-fallback"


def ensure_channel(root: ET.Element, channel_id: str, display_name: str) -> ET.Element:
    channel = next((c for c in root.findall("channel") if c.get("id") == channel_id), None)
    if channel is None:
        channel = ET.Element("channel", {"id": channel_id})
        root.insert(len(root.findall("channel")), channel)
    names = {(n.text or "").strip() for n in channel.findall("display-name")}
    if display_name not in names:
        ET.SubElement(channel, "display-name").text = display_name
    return channel


def main(guide_path: Path, config_path: Path) -> None:
    tree = ET.parse(guide_path)
    root = tree.getroot()
    with config_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        expected = ["channel_id", "display_name", "source_page", "fallback_logo"]
        if reader.fieldnames != expected:
            raise ValueError(f"Unexpected CSV header: {reader.fieldnames!r}")
        rows = list(reader)

    for row in rows:
        cid = row["channel_id"].strip()
        name = row["display_name"].strip()
        page = row["source_page"].strip()
        fallback = row["fallback_logo"].strip()
        logo, method = resolved_logo(page, fallback)
        channel = ensure_channel(root, cid, name)
        for icon in list(channel.findall("icon")):
            channel.remove(icon)
        ET.SubElement(channel, "icon", {"src": logo})
        print(f"music logo {cid}: {method} -> {logo}")

    ET.indent(tree, space="  ")
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: resolve_music_logos.py guide.xml music-logo-sources.csv")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
