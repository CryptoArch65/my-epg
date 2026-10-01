#!/usr/bin/env python3
"""Use MAXtv's public channel catalogue for the selected Croatian logos."""

import csv
import hashlib
import json
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen


CHANNELS = {
    '311618600203': 'RTLAdria.hr',
    '338263080036': 'DiadoraTV.hr',
    '276770856251': 'SportskaTV.hr',
}
API = ('https://tv-hr-prod.yo-digital.com/hr-bifrost/epg/channel'
       '?channelMap_id=&includeVirtualChannels=false'
       '&natco_key={}&app_language=hr&natco_code=hr')
LOGO_PREFIX = 'https://tv-hr-prod.yo-digital.com/prod/images/logos/'


def js_constant(source, name):
    match = re.search(r'const\s+' + name + r"\s*=\s*['\"]([^'\"]+)['\"]", source)
    if not match:
        raise ValueError(f'MAXtv configuration has no {name}')
    return match.group(1)


def ensure_epg_days(config_path, days=3):
    content = config_path.read_text(encoding='utf-8')
    if re.search(r'(?m)^\s*days:\s*\d+\s*,', content):
        content = re.sub(r'(?m)^(\s*)days:\s*\d+\s*,', rf'\1days: {days},', content, count=1)
    else:
        marker = 'module.exports = {\n  site: SITE_URL,'
        replacement = f'module.exports = {{\n  site: SITE_URL,\n  days: {days},'
        if content.count(marker) != 1:
            raise ValueError('MAXtv config structure changed upstream')
        content = content.replace(marker, replacement, 1)
    config_path.write_text(content, encoding='utf-8')
    print(f'Configured MAXtv EPG for {days} days')


def image_url(value):
    if isinstance(value, str):
        return value if value.startswith(LOGO_PREFIX) else None
    if isinstance(value, list):
        return next((url for item in value if (url := image_url(item))), None)
    if isinstance(value, dict):
        for key in ('url', 'src', 'path', 'image', 'logo'):
            if key in value and (url := image_url(value[key])):
                return url
        return next((url for item in value.values() if (url := image_url(item))), None)
    return None


def official_logos(config_path):
    config = config_path.read_text(encoding='utf-8')
    app_key = js_constant(config, 'APP_KEY')
    version = js_constant(config, 'APP_VERSION')
    natco_key = js_constant(config, 'NATCO_KEY')
    device = str(uuid.uuid4())
    session = str(uuid.uuid4())
    tracking = str(uuid.uuid4())
    call_time = str(int(time.time() * 1000))
    headers = {
        'app_key': app_key,
        'app_version': version,
        'device-id': device,
        'tenant': 'tv',
        'User-Agent': 'Mozilla/5.0',
        'Origin': 'https://mojmaxtv.hrvatskitelekom.hr',
        'x-call-type': 'GUEST_USER',
        'x-call-time': call_time,
        'x-request-session-id': session,
        'x-request-tracking-id': tracking,
        'x-tv-step': 'EPG_SCHEDULES',
        'x-tv-flow': 'EPG',
        'x-txn-id': hashlib.sha256((tracking + session + device + call_time).encode()).hexdigest()[:32],
        'x-user-agent': f'web|web|Chrome-149|{version}|1',
    }
    request = Request(API.format(natco_key), headers=headers)
    with urlopen(request, timeout=35) as response:
        data = json.load(response)
    records = data if isinstance(data, list) else data.get('channels', [])
    if not isinstance(records, list):
        raise ValueError('MAXtv returned no channel list')
    logos = {}
    for row in records:
        if not isinstance(row, dict) or str(row.get('station_id')) not in CHANNELS:
            continue
        logo = image_url(row.get('images')) or image_url(row.get('logo')) or image_url(row)
        if logo:
            logos[CHANNELS[str(row['station_id'])]] = logo
    if set(logos) != set(CHANNELS.values()):
        raise ValueError('MAXtv channel logos missing for ' + ', '.join(sorted(set(CHANNELS.values()) - set(logos))))
    return logos


def main(config_path, csv_path):
    ensure_epg_days(config_path, 3)
    with csv_path.open(newline='', encoding='utf-8') as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ['guide_id', 'logo_url']:
            raise ValueError('Unexpected logo CSV header')
        rows = list(reader)
    by_id = {row['guide_id']: row for row in rows}
    if set(CHANNELS.values()) - set(by_id):
        raise ValueError('MAXtv logo mappings missing from CSV')
    try:
        logos = official_logos(config_path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f'Warning: MAXtv logo catalogue unavailable; keeping existing logos: {exc}')
        return
    for channel_id, url in logos.items():
        by_id[channel_id]['logo_url'] = url
    with csv_path.open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=['guide_id', 'logo_url'], lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    print('Updated official MAXtv logos for ' + ', '.join(sorted(logos)))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: import_maxtv_channel_logos.py epg/sites/...config.js config/bih-source-logos.csv')
    main(Path(sys.argv[1]), Path(sys.argv[2]))
