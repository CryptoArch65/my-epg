#!/usr/bin/env python3
"""Attach verified provider logos to XMLTV channels before copying aliases."""
import csv
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse


def main(guide_path, logos_path):
    tree = ET.parse(guide_path)
    root = tree.getroot()
    if root.tag != 'tv':
        raise ValueError('Expected XMLTV <tv> root')
    channels = {channel.get('id'): channel for channel in root.findall('channel')}
    if len(channels) != len(root.findall('channel')):
        raise ValueError('Duplicate XMLTV channel ID')

    seen = set()
    with open(logos_path, encoding='utf-8', newline='') as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ['guide_id', 'logo_url']:
            raise ValueError('Unexpected logo CSV header')
        for row in reader:
            channel_id = row['guide_id'].strip()
            url = row['logo_url'].strip()
            parsed = urlparse(url)
            if (not channel_id or channel_id in seen or channel_id not in channels
                    or parsed.scheme != 'https' or not parsed.netloc):
                raise ValueError(f'Invalid provider logo for {channel_id!r}')
            seen.add(channel_id)
            channel = channels[channel_id]
            for icon in channel.findall('icon'):
                channel.remove(icon)
            channel.append(ET.Element('icon', {'src': url}))

    tree.write(guide_path, encoding='utf-8', xml_declaration=True)
    print(f'Added verified source logos to {len(seen)} XMLTV channels')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: add_channel_logos.py guide.xml config/bih-source-logos.csv')
    main(*sys.argv[1:])
