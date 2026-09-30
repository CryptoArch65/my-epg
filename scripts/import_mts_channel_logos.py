#!/usr/bin/env python3
"""Use public MTS channel catalogue logos for RTS and Prva MAX/Life."""

import csv
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse
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
    'prva_files': 'PrvaFiles.rs',
    'rtv_1': 'RTV1.rs',
    'rtv_2': 'RTV2.rs',
    'tv_sandzak': 'SandzakTV.rs',
    'studio_b': 'StudioB.rs',
    'tv_palma_plus': 'PalmaPlus.rs',
    'tv_istok': 'TVIstok.rs',
    'tv_leskovac': 'TVLeskovac.rs',
    'tv_hram': 'TVHram.rs',
    'tv_krusevac': 'TVKrusevac.rs',
    'tanjug_tv': 'TanjugTV.rs',
    'TV%20Jefimija': 'JefimijaTV.rs',
    'euronews_serbia': 'EuronewsSerbia.rs',
    'Informer%20TV': 'InformerTV.rs',
    'una_tv': 'UnaTV.rs',
    'kurir_hd': 'KurirTV.rs',
    'blic_tv': 'BlicTV.rs',
    'k1_hd': 'K1.rs',
}
URL = ('https://mts.rs/hybris/ecommerce/b2c/v1/products/search'
       '?sort=pozicija-rastuce&searchQueryContext=CHANNEL_PROGRAM'
       '&query=:pozicija-rastuce:tip-kanala-radio:TV%20kanali'
       ':channelProgramDates:{}&pageSize=10000')
MTEL_URL = ('https://mtel.ba/hybris/ecommerce/b2c/v1/products/channels/search'
            '?pageSize=999&query=:relevantno:tv-kategorija:tv-iptv')
MTEL_CHANNELS = {
    'iptv#ch-411-k1': 'K1.rs',
    'iptv#ch-20-rts-2': 'RTS2.rs',
    'iptv#ch-50-rts-muzika': 'RTSMuzika.rs',
    'iptv#ch-433-rts-klasika': 'RTSKlasika.rs',
    'iptv#ch-21-rts-nauka-hd': 'RTSNauka.rs',
    'iptv#ch-388-rts-poletarac': 'RTSPoletarac.rs',
    'iptv#ch-49-rts-trezor': 'RTSTrezor.rs',
    'iptv#ch-45-rts-zivot': 'RTSZivot.rs',
    'iptv#ch-19-rts-svet': 'RTSSvet.rs',
    'iptv#ch-360-prva-max': 'PrvaMax.rs',
    'iptv#ch-363-prva-life': 'PrvaLife.rs',
}


def first_url(value, base=''):
    if isinstance(value, str):
        if value.startswith('https://'):
            return value
        return urljoin(base, value) if base and value.startswith('/') else None
    if isinstance(value, list):
        return next((url for item in value if (url := first_url(item, base))), None)
    if isinstance(value, dict):
        for key in ('url', 'src', 'path', 'image', 'logo'):
            if key in value and (url := first_url(value[key], base)):
                return url
        return next((url for item in value.values() if (url := first_url(item, base))), None)
    return None


def official_logos():
    date = datetime.now(ZoneInfo('Europe/Belgrade')).strftime('%Y-%m-%d')
    request = Request(URL.format(date), headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
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
        channel_id = CHANNELS.get(code) or CHANNELS.get(unquote(code)) or CHANNELS.get(quote(code))
        if not channel_id:
            continue
        logo = (first_url(row.get('picture'), 'https://mts.rs')
                or first_url(row.get('images'), 'https://mts.rs')
                or first_url(row.get('logo'), 'https://mts.rs'))
        if logo and urlparse(logo).hostname in {'mts.rs', 'www.mts.rs', 'medias.services.mts.rs', 'mediasb2c.mts.rs'}:
            logos[channel_id] = logo
    return logos


def mtel_logos():
    request = Request(MTEL_URL, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    with urlopen(request, timeout=35) as response:
        data = json.load(response)
    products = data.get('products') if isinstance(data, dict) else data
    if not isinstance(products, list):
        raise ValueError('m:tel returned no channel products')
    logos = {}
    for row in products:
        if not isinstance(row, dict):
            continue
        channel_id = MTEL_CHANNELS.get('iptv#' + str(row.get('code')))
        if not channel_id:
            continue
        logo = first_url(row.get('picture'), 'https://mtel.ba') or first_url(row.get('images'), 'https://mtel.ba')
        if logo and urlparse(logo).hostname in {'mtel.ba', 'www.mtel.ba', 'medias.services.mtel.ba'}:
            logos[channel_id] = logo
    return logos


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
    mtel = {}
    try:
        mtel = mtel_logos()
        for channel_id, logo in mtel.items():
            by_id[channel_id]['logo_url'] = logo
        print(f'Updated {len(mtel)} official m:tel channel logos')
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f'Warning: m:tel logo catalogue unavailable; keeping existing logos: {exc}')
    missing = set(CHANNELS.values()) - set(logos) - set(mtel)
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
