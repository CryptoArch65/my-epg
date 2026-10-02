#!/usr/bin/env python3
"""Import Cinemania HD (BIH) EPG and logo directly from Telemach."""

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SITE_ID = "1522"
GUIDE_ID = "CinemaniaHD.ba"
API = "https://api-web.ug-be.cdn.united.cloud"
IMAGE_BASE = "https://images-web.ug-be.cdn.united.cloud"
BASIC_TOKEN = "MjdlMTFmNWUtODhlMi00OGU0LWJkNDItOGUxNWFiYmM2NmY1OjEyejJzMXJ3bXdhZmsxMGNkdzl0cjloOWFjYjZwdjJoZDhscXZ0aGc="
TZ = ZoneInfo("Europe/Sarajevo")


def request_json(url, headers, data=None):
    req = Request(url, headers=headers, data=data)
    with urlopen(req, timeout=40) as response:
        return json.load(response)


def token():
    data = request_json(
        API + "/oauth/token?grant_type=client_credentials",
        {"Authorization": f"Basic {BASIC_TOKEN}"},
        data=b"{}",
    )
    value = data.get("access_token")
    if not value:
        raise ValueError("Telemach access token missing")
    return value


def logo_for(channel):
    images = channel.get("images") or []
    candidates = [item for item in images if isinstance(item, dict) and item.get("path")]
    candidates.sort(
        key=lambda item: (
            "LOGO" not in str(item.get("type", "")).upper(),
            "LOGO" not in str(item.get("legacyType", "")).upper(),
        )
    )
    if not candidates:
        raise ValueError("Cinemania HD has no Telemach logo image")
    return urljoin(IMAGE_BASE, candidates[0]["path"])


def parse_time(value):
    text = str(value or "").replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)


def ensure_channel(root, logo):
    channel = next((c for c in root.findall("channel") if c.get("id") == GUIDE_ID), None)
    if channel is None:
        channel = ET.Element("channel", {"id": GUIDE_ID})
        root.insert(len(root.findall("channel")), channel)

    wanted_names = ("Cinemania HD", "Cinemania HD (BIH)", "Cinemania ᴴᴰ")
    existing = {(n.text or "").strip() for n in channel.findall("display-name")}
    for name in wanted_names:
        if name not in existing:
            ET.SubElement(channel, "display-name", {"lang": "hr"}).text = name

    for icon in list(channel.findall("icon")):
        channel.remove(icon)
    ET.SubElement(channel, "icon", {"src": logo})
    return channel


def main(path):
    access = token()
    headers = {
        "Authorization": f"Bearer {access}",
        "Referer": "https://epg.telemach.ba/",
        "User-Agent": "Mozilla/5.0 (EPG guide)",
    }

    channels_url = API + "/v1/public/channels?" + urlencode(
        {
            "channelType": "TV",
            "communityId": 12,
            "languageId": 59,
            "imageSize": "L",
        }
    )
    channels = request_json(channels_url, headers)
    channel = next((c for c in channels if str(c.get("id")) == SITE_ID), None)
    if channel is None:
        raise ValueError("Telemach channel 1522 missing")
    if "cinemania" not in str(channel.get("name") or "").casefold():
        raise ValueError(f"Unexpected Telemach channel 1522: {channel.get('name')!r}")
    logo = logo_for(channel)

    today = datetime.now(TZ).date()
    events = {}
    for offset in range(3):
        day = today + timedelta(days=offset)
        start = datetime(day.year, day.month, day.day, tzinfo=TZ)
        stop = start + timedelta(days=1) - timedelta(seconds=1)
        params = {
            "fromTime": start.strftime("%Y-%m-%dT%H:%M:%S-00:00"),
            "toTime": stop.strftime("%Y-%m-%dT%H:%M:%S-00:00"),
            "communityId": 12,
            "languageId": 59,
            "cid": SITE_ID,
        }
        data = request_json(API + "/v1/public/events/epg?" + urlencode(params), headers)
        for items in data.values() if isinstance(data, dict) else []:
            if not isinstance(items, list):
                continue
            for item in items:
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                try:
                    event_start = parse_time(item.get("startTime"))
                    event_stop = parse_time(item.get("endTime"))
                except Exception:
                    continue
                if event_stop <= event_start:
                    continue
                key = (event_start, event_stop, title)
                events[key] = item

    if len(events) < 5:
        raise ValueError(f"Cinemania HD Telemach EPG too short: {len(events)}")

    tree = ET.parse(path)
    root = tree.getroot()
    ensure_channel(root, logo)

    for programme in list(root.findall("programme")):
        if programme.get("channel") == GUIDE_ID:
            root.remove(programme)

    for (start, stop, title), item in sorted(events.items(), key=lambda row: row[0][0]):
        programme = ET.SubElement(
            root,
            "programme",
            {
                "channel": GUIDE_ID,
                "start": start.strftime("%Y%m%d%H%M%S %z"),
                "stop": stop.strftime("%Y%m%d%H%M%S %z"),
            },
        )
        ET.SubElement(programme, "title", {"lang": "hr"}).text = title
        desc = str(item.get("shortDescription") or "").strip()
        if desc:
            ET.SubElement(programme, "desc", {"lang": "hr"}).text = desc
        season = item.get("seasonNumber")
        episode = item.get("episodeNumber")
        if season not in (None, "") or episode not in (None, ""):
            s = int(season or 1) - 1
            e = int(episode or 1) - 1
            ET.SubElement(programme, "episode-num", {"system": "xmltv_ns"}).text = f"{s}.{e}."
        images = item.get("images") or []
        if isinstance(images, list) and images and isinstance(images[0], dict) and images[0].get("path"):
            ET.SubElement(programme, "icon", {"src": urljoin(IMAGE_BASE, images[0]["path"])})

    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"Cinemania HD: Telemach site_id={SITE_ID}, programmes={len(events)}, logo={logo}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_cinemania_telemach.py guide.xml")
    main(Path(sys.argv[1]))
