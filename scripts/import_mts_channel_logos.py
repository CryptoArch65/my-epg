#!/usr/bin/env python3
"""Use public MTS channel catalogue logos for RTS and Prva MAX/Life."""

import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


CHANNELS = {
    'rts_1_hd': 'RTS1.rs',
    'rts_2_hd': 'RTS2.rs',
    'rts_3_hd': 'RTS3.rs',
    'rts_drama': 'RTSDrama.rs',
    'rts_klasika': 'RTSKlasika.rs',
    'rts_kolo': 'RTSKolo.rs',
    'rts_muzika': 'RTSMuzika.rs',
    'rts_nauka': 'RTSNauka.rs',
    'rts_poletarac': 'RTSPoletarac.rs',
    'rts_trezor': 'RTSTrezor.rs',
    'rts_zivot': 'RTSZivot.rs',
    'Prva%20MAX': 'PrvaMax.rs',
    'prva_life': 'PrvaLife.rs',
}
URL = ('https://mts.rs/hybris/ecommerce/b2c/v1/products/search'
       '?sort=pozicija-rastuce&searchQueryContext=CHANNEL_PROGRAM'
       '&query=:pozicija-rastuce:tip-kanala-radio:TV%20kanali&pageSize=10000')
MTEL_URL = ('https://mtel.ba/hybris/ecommerce/b2c/v1/products/channels/search'
            '?pageSize=999&query=:relevantno:tv-kategorija:tv-iptv')


def first_url(value):
    if isinstance(value, str):
        return value if value.startswith('https://') else None
    if isinstance(value, list):
        return next((url for item in value if (url := first_url(item))), None)
    if isinstance(value, dict):
        for key in ('url', 'src', 'path', 'image', 'logo'):
            if key in value and (url := first_url(value[key])):
                return url
        return next((url for item in value.values() if (url := first_url(item))), None)
    return None


def official_logos():
    request = Request(URL, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    with urlopen(request, timeout=35) as response:
        data = json.load(response)
    products = data.get('products') if isinstance(data, dict) else data
    if not isinstance(products, list):
        raise ValueError('MTS returned no channel products')
    logos = {}
    for row in products:
        if not isinstance(row, dict):
            continue
        code = str(row.get('code', ''))
        if code not in CHANNELS:
            continue
        logo = first_url(row.get('picture')) or first_url(row.get('images')) or first_url(row.get('logo'))
        if logo and urlparse(logo).hostname in {'mts.rs', 'www.mts.rs', 'medias.services.mts.rs'}:
            logos[CHANNELS[code]] = logo
    return logos


def svet_logo():
    request = Request(MTEL_URL, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    with urlopen(request, timeout=35) as response:
        data = json.load(response)
    products = data.get('products') if isinstance(data, dict) else data
    if not isinstance(products, list):
        return None
    for row in products:
        if isinstance(row, dict) and str(row.get('code')) == 'iptv#ch-19-rts-svet':
            logo = first_url(row.get('picture')) or first_url(row.get('images'))
            if logo and urlparse(logo).hostname in {'mtel.ba', 'www.mtel.ba', 'medias.services.mtel.ba'}:
                return logo
    return None


def main(csv_path):
    with csv_path.open(newline='', encoding='utf-8') as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ['guide_id', 'logo_url']:
            raise ValueError('Unexpected logo CSV header')
        rows = list(reader)
    by_id = {row['guide_id']: row for row in rows}
    if set(CHANNELS.values()) - set(by_id):
        raise ValueError('MTS channel logo mappings missing from CSV')
    try:
        logos = official_logos()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f'Warning: MTS logo catalogue unavailable; keeping existing logos: {exc}')
        return
    for channel_id, logo in logos.items():
        by_id[channel_id]['logo_url'] = logo
    try:
        svet = svet_logo()
        if svet:
            by_id['RTSSvet.rs']['logo_url'] = svet
            print('Updated official m:tel logo for RTS Svet')
        else:
            print('Warning: m:tel RTS Svet logo unavailable; keeping existing logo')
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f'Warning: m:tel RTS Svet logo unavailable; keeping existing logo: {exc}')
    missing = set(CHANNELS.values()) - set(logos)
    if missing:
        print('Warning: MTS has no matching logo for ' + ', '.join(sorted(missing)))
    with csv_path.open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=['guide_id', 'logo_url'], lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    print(f'Updated {len(logos)} official MTS channel logos')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: import_mts_channel_logos.py config/bih-source-logos.csv')
    main(Path(sys.argv[1]))
