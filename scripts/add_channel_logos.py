#!/usr/bin/env python3
"""Attach verified provider logos to XMLTV channels before copying aliases."""
import csv
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

PLAYLIST_NAMES = {
    'Hayat.ba': ('|BIH| HAYAT BIH', '|BIH| HAYAT BiH HD'),
    'FACETV.ba': ('|BIH| FACE TV', '|BIH| FACE TV HD'),
    'RTL2.hr': ('|HR| RTL 2', '|HR| RTL 2 HD'),
    'PrvaFiles.rs': ("|SRB| PRVA FILES",),
    'RTV1.rs': ("|SRB| RTV VOJVODINA 1",),
    'RTV2.rs': ("|SRB| RTV VOJVODINA 2",),
    'SandzakTV.rs': ("|SRB| SANDZAK TV",),
    'StudioB.rs': ("|SRB| STUDIO B",),
    'PalmaPlus.rs': ("|SRB| PALMA PLUS JAGODINA",),
    'TVIstok.rs': ("|SRB| TV ISTOK 1",),
    'TVLeskovac.rs': ("|SRB| LESKOVAC",),
    'TVHram.rs': ("|SRB| HRAM",),
    'TVKrusevac.rs': ("|SRB| RTV KRUSEVAC",),
    'TanjugTV.rs': ("|SRB| TANJUG HD",),
    'JefimijaTV.rs': ("|SRB| JEFIMIJA TV",),
    'EuronewsSerbia.rs': ("|SRB| EURONEWS SERBIA HD",),
    'N1Serbia.rs': ("|SRB| N1 INFO",),
    'RTVNoviPazar.rs': ("|SRB| RTV NOVI PAZAR",),
    'ArenaSport4.ba': ('|BH| ARENA SPORT 4',),
    'ArenaSport5BH.ba': ('|BH| ARENA SPORT 5',),
    'NovaS.rs': ('|SRB| NOVA S', '|SRB| NOVA S HD'),
    'UnaTV.rs': ('|SRB| UNA TV',),
    'KurirTV.rs': ('|SRB| KURIR TV',),
    'BlicTV.rs': ('|SRB| BLIC TV',),
    'K1.rs': ('|SRB| K1 TV',),
    'Prva.rs': ('|SRB| PRVA TV', '|SRB| PRVA TV HD'),
    'PrvaPlus.rs': ('|SRB| PRVA PLUS', '|SRB| PRVA PLUS HD'),
    'PrvaWorld.rs': ('|SRB| PRVA WORLD', '|SRB| PRVA WORLD HD'),
    'PrvaKick.rs': ('|SRB| PRVA KICK', '|SRB| PRVA KICK HD'),
    'PrvaMax.rs': ('|SRB| PRVA MAX', '|SRB| PRVA MAX HD'),
    'PrvaLife.rs': ('|SRB| PRVA LIFE',),
    'RTS1.rs': ('|SRB| RTS 1', '|SRB| RTS 1 HD'),
    'RTS2.rs': ('|SRB| RTS 2', '|SRB| RTS 2 HD'),
    'RTS3.rs': ('|SRB| RTS 3',),
    'RTSMuzika.rs': ('|SRB| RTS MUZIKA',),
    'RTSSvet.rs': ('|SRB| RTS SVET',),
    'RTLAdria.hr': ('|HR| RTL ADRIA',),
    'SportskaTV.hr': ('SPORTSKA TV',),
}


def main(guide_path, logos_path):
    tree = ET.parse(guide_path)
    root = tree.getroot()
    if root.tag != 'tv':
        raise ValueError('Expected XMLTV <tv> root')
    channels = {channel.get('id'): channel for channel in root.findall('channel')}
    if len(channels) != len(root.findall('channel')):
        raise ValueError('Duplicate XMLTV channel ID')

    seen = set()
    applied = 0
    with open(logos_path, encoding='utf-8', newline='') as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ['guide_id', 'logo_url']:
            raise ValueError('Unexpected logo CSV header')
        for row in reader:
            channel_id = row['guide_id'].strip()
            url = row['logo_url'].strip()
            parsed = urlparse(url)
            if (not channel_id or channel_id in seen
                    or parsed.scheme != 'https' or not parsed.netloc):
                raise ValueError(f'Invalid provider logo for {channel_id!r}')
            seen.add(channel_id)
            channel = channels.get(channel_id)
            if channel is None:
                print(f'WARNING: Logo mapping has no channel in this guide: {channel_id}')
                continue
            for icon in channel.findall('icon'):
                channel.remove(icon)
            channel.append(ET.Element('icon', {'src': url}))
            applied += 1

    for channel_id, names in PLAYLIST_NAMES.items():
        channel = channels.get(channel_id)
        if channel is None:
            raise ValueError(f'Missing channel for playlist names: {channel_id}')
        present = {element.text for element in channel.findall('display-name')}
        for name in names:
            if name not in present:
                ET.SubElement(channel, 'display-name', {'lang': 'hr'}).text = name

    tree.write(guide_path, encoding='utf-8', xml_declaration=True)
    print(f'Added verified source logos to {applied} XMLTV channels')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: add_channel_logos.py guide.xml config/bih-source-logos.csv')
    main(*sys.argv[1:])
