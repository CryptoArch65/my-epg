#!/usr/bin/env python3
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta, datetime

BASE = 'https://mts.rs/hybris/ecommerce/b2c/v1/products/search'
CHANNELS = [
    {'codes': {'ha_ha'}, 'names': {'ha ha','haha'}, 'xmltv_id': 'pink-ha-ha', 'display': 'HA HA'},
    {'codes': {'lol'}, 'names': {'lol'}, 'xmltv_id': 'pink-lol', 'display': 'LOL'},
]


def fetch_page(day, page):
    query = f':pozicija-rastuce:tip-kanala-radio:TV kanali:channelProgramDates:{day}'
    url = BASE + '?' + urllib.parse.urlencode({
        'sort': 'pozicija-rastuce',
        'searchQueryContext': 'CHANNEL_PROGRAM',
        'query': query,
        'pageSize': '50',
        'currentPage': str(page),
    })
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def norm(s):
    return ''.join(ch.lower() for ch in str(s or '') if ch.isalnum())


def fmt_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.strftime('%Y%m%d%H%M%S %z')
    except Exception:
        return None


def all_products(day):
    out = []
    page = 0
    while page < 30:
        data = fetch_page(day, page)
        products = data.get('products') or []
        pagination = data.get('pagination') or {}
        print(f"MTS EPG {day} page={page}: products={len(products)} pagination={pagination}")
        out.extend(products)
        if not products:
            break
        total_pages = pagination.get('totalPages')
        current_page = pagination.get('currentPage', page)
        if isinstance(total_pages, int) and current_page + 1 >= total_pages:
            break
        if len(products) < 50 and total_pages is None:
            break
        page += 1
    return out


def find_product(products, ch):
    wanted_codes = {norm(x) for x in ch['codes']}
    wanted_names = {norm(x) for x in ch['names']}
    for p in products:
        if norm(p.get('code')) in wanted_codes or norm(p.get('name')) in wanted_names:
            return p
    return None


def main():
    root = ET.Element('tv', {'generator-info-name': 'custom-mts-pink-paginated'})
    for ch in CHANNELS:
        ce = ET.SubElement(root, 'channel', {'id': ch['xmltv_id']})
        ET.SubElement(ce, 'display-name', {'lang': 'bs'}).text = ch['display']

    counts = {c['xmltv_id']: 0 for c in CHANNELS}

    for offset in range(2):
        day = (date.today() + timedelta(days=offset)).isoformat()
        products = all_products(day)
        print(f"MTS EPG {day}: total collected products={len(products)}")
        for ch in CHANNELS:
            wanted = find_product(products, ch)
            if not wanted:
                print(f"MTS {ch['display']} {day}: NOT FOUND")
                continue
            programs = wanted.get('programs') or []
            print(f"MTS {ch['display']} {day}: name={wanted.get('name')!r} code={wanted.get('code')!r} programs={len(programs)}")
            for item in programs:
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
