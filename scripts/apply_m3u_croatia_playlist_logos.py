#!/usr/bin/env python3
"""Apply hosted Croatia M3U logos directly to playlist tvg-id channel entries in XMLTV."""
import csv
import hashlib
import io
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from PIL import Image

RAW_BASE = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/"


def fetch(source, target):
    if target.is_file():
        return True, "cached"
    parts = urlsplit(source)
    safe_url = urlunsplit((parts.scheme, parts.netloc, quote(parts.path), parts.query, parts.fragment))
    last_error = None
    for _ in range(2):
        try:
            req = Request(safe_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
            with urlopen(req, timeout=20) as response:
                data = response.read(3_000_001)
            if len(data) > 3_000_000:
                raise ValueError("logo exceeds 3 MB")
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 25_000_000:
                    raise ValueError("logo dimensions too large")
                converted = image.convert("RGBA")
                converted.thumbnail((1024, 1024))
                output = io.BytesIO()
                converted.save(output, format="PNG")
            target.write_bytes(output.getvalue())
            return True, f"hosted {len(output.getvalue())} bytes"
        except Exception as exc:
            last_error = exc
    return False, str(last_error)


def main(guide_path, manifest_path, logos_dir):
    with manifest_path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    expected = ["playlist_tvg_id", "display_name", "m3u_channel", "logo_url"]
    if not rows or list(rows[0]) != expected:
        raise ValueError("Unexpected Croatia playlist logo manifest header")
    ids = [row["playlist_tvg_id"].strip() for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Invalid or duplicate Croatia playlist tvg-id")

    logos_dir.mkdir(parents=True, exist_ok=True)
    targets = {
        url: logos_dir / ("m3u-croatia-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".png")
        for url in {row["logo_url"].strip() for row in rows}
    }
    results = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(fetch, url, target): url for url, target in targets.items()}
        for job in as_completed(jobs):
            url = jobs[job]
            results[url] = job.result()
            print(f"Croatia playlist logo {url}: {results[url][1]}")

    tree = ET.parse(guide_path)
    root = tree.getroot()
    if root.tag != "tv":
        raise ValueError("Expected XMLTV <tv> root")
    channels = {node.get("id"): node for node in root.findall("channel")}
    insert_at = len(root.findall("channel"))

    updated = created = unavailable = 0
    for row in rows:
        channel_id = row["playlist_tvg_id"].strip()
        display_name = row["display_name"].strip()
        source_url = row["logo_url"].strip()
        if not results[source_url][0]:
            unavailable += 1
            continue
        logo_url = RAW_BASE + targets[source_url].name
        channel = channels.get(channel_id)
        if channel is None:
            channel = ET.Element("channel", {"id": channel_id})
            name = ET.SubElement(channel, "display-name")
            name.text = display_name
            ET.SubElement(channel, "icon", {"src": logo_url})
            root.insert(insert_at, channel)
            insert_at += 1
            channels[channel_id] = channel
            created += 1
        else:
            icons = channel.findall("icon")
            if icons:
                icons[0].set("src", logo_url)
                for extra in icons[1:]:
                    channel.remove(extra)
            else:
                channel.append(ET.Element("icon", {"src": logo_url}))
            updated += 1

    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(f"Croatia playlist logos: {updated} existing channels updated; {created} logo-only channels added; {unavailable} unavailable")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: apply_m3u_croatia_playlist_logos.py guide.xml manifest.csv logos/")
    main(*(Path(value) for value in sys.argv[1:]))
