#!/usr/bin/env python3
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from lxml import html

ZONE = ZoneInfo('Europe/Zagreb')
CHANNEL_ID = 'nova-plus-cinema'
BASE = 'https://raspored.tv/nova-cinema'


def fetch(url):
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0 (EPG guide)'})
    with urlopen(req, timeout=30) as r:
        return r.read()


def parse_day(day):
    tree = html.fromstring(fetch(f'{BASE}/{day.isoformat()}'))
    tokens = [' '.join(t.split()) for t in tree.xpath('//text()')]
    tokens = [t for t in tokens if t]
    events = []
    for i, token in enumerate(tokens):
        if not re.fullmatch(r'[0-2]\d:[0-5]\d', token):
            continue
        title = None
        for nxt in tokens[i+1:i+8]:
            if re.fullmatch(r'[0-2]\d:[0-5]\d', nxt):
                break
            if re.search(r'\b\d{2}:\d{2}\s*[–-]\s*\d{2}:\d{2}\b', nxt):
                continue
            if len(nxt) >= 2 and not re.fullmatch(r'\d+\s*min', nxt, re.I):
                title = nxt
                break
        if not title:
            continue
        start = datetime.strptime(f'{day} {token}', '%Y-%m-%d %H:%M').replace(tzinfo=ZONE)
        events.append((start, title))
    dedup = {}
    for start, title in events:
        dedup.setdefault(start, title)
    return sorted(dedup.items())


def main(path):
    tree = ET.parse(path)
    root = tree.getroot()
    for p in list(root.findall('programme')):
        if p.get('channel') == CHANNEL_ID:
            root.remove(p)
    channel = next((c for c in root.findall('channel') if c.get('id') == CHANNEL_ID), None)
    if channel is None:
        channel = ET.Element('channel', {'id': CHANNEL_ID})
        ET.SubElement(channel, 'display-name').text = '|HR| NOVA CINEMA HD'
        root.insert(len(root.findall('channel')), channel)
    today = datetime.now(ZONE).date()
    all_events = []
    for offset in range(5):
        all_events.extend(parse_day(today + timedelta(days=offset)))
    all_events = sorted(dict(all_events).items())
    if len(all_events) < 10:
        raise SystemExit(f'Nova Cinema scrape returned too few programmes: {len(all_events)}')
    for idx, (start, title) in enumerate(all_events):
        stop = all_events[idx + 1][0] if idx + 1 < len(all_events) else start + timedelta(hours=2)
        if stop <= start:
            continue
        p = ET.SubElement(root, 'programme', {
            'channel': CHANNEL_ID,
            'start': start.strftime('%Y%m%d%H%M%S %z'),
            'stop': stop.strftime('%Y%m%d%H%M%S %z'),
        })
        ET.SubElement(p, 'title', {'lang': 'hr'}).text = title
    tree.write(path, encoding='utf-8', xml_declaration=True)
    print(f'Nova Cinema: imported {len(all_events)} programmes from raspored.tv')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
