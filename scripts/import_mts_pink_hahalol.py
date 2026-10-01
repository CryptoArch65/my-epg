#!/usr/bin/env python3
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta, datetime

BASE = 'https://mts.rs/hybris/ecommerce/b2c/v1/products/search'
CHANNELS = [
    {'search': 'ha ha', 'names': {'ha ha','haha'}, 'xmltv_id': 'pink-ha-ha', 'display': 'HA HA'},
    {'search': 'lol', 'names': {'lol'}, 'xmltv_id': 'pink-lol', 'display': 'LOL'},
]


def fetch(search, day):
    query = f':{search}:pozicija-rastuce:tip-kanala-radio:TV kanali:channelProgramDates:{day}'
    url = BASE + '?' + urllib.parse.urlencode({
        'sort': 'pozicija-rastuce',
        'searchQueryContext': 'CHANNEL_PROGRAM',
        'query': query,
        'pageSize': '10000',
    })
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def norm(s):
    return ''.join(ch.lower() for ch in str(s or '') if ch.isalnum())


def fmt_dt(value):
    if not value:
        return None
    s = str(value)
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return dt.strftime('%Y%m%d%H%M%S %z')
    except Exception:
        return None


def main():
    root = ET.Element('tv', {'generator-info-name': 'custom-mts-pink'})
    for ch in CHANNELS:
        ce = ET.SubElement(root, 'channel', {'id': ch['xmltv_id']})
        ET.SubElement(ce, 'display-name', {'lang': 'bs'}).text = ch['display']

    counts = {c['xmltv_id']: 0 for c in CHANNELS}

    for offset in range(2):
        day = (date.today() + timedelta(days=offset)).isoformat()
        for ch in CHANNELS:
            data = fetch(ch['search'], day)
            products = data.get('products') or []
            wanted = None
            for p in products:
                name_n = norm(p.get('name'))
                code_n = norm(p.get('code'))
                if name_n in {norm(x) for x in ch['names']} or code_n in {norm(x) for x in ch['names']}:
                    wanted = p
                    break
            if wanted is None and len(products) == 1:
                wanted = products[0]
            print(f"MTS direct {ch['display']} {day}: products={[(p.get('name'), p.get('code'), len(p.get('programs') or [])) for p in products]}")
            if not wanted:
                continue
            for item in wanted.get('programs') or []:
                start = fmt_dt(item.get('start'))
                stop = fmt_dt(item.get('end'))
                if not start or not stop:
                    continue
                pe = ET.SubElement(root, 'programme', {
                    'start': start,
                    'stop': stop,
                    'channel': ch['xmltv_id'],
                })
                ET.SubElement(pe, 'title', {'lang': 'bs'}).text = str(item.get('title') or '')
                desc = item.get('description')
                if desc:
                    ET.SubElement(pe, 'desc', {'lang': 'bs'}).text = str(desc)
                cat = item.get('category')
                if cat:
                    ET.SubElement(pe, 'category', {'lang': 'bs'}).text = str(cat)
                counts[ch['xmltv_id']] += 1

    ET.indent(root, space='  ')
    ET.ElementTree(root).write('pink-hahalol-mts.xml', encoding='utf-8', xml_declaration=True)
    print('Pink HA HA/LOL counts:', counts)
    missing = [cid for cid, n in counts.items() if n == 0]
    if missing:
        raise SystemExit('No programmes for: ' + ', '.join(missing))


if __name__ == '__main__':
    main()
