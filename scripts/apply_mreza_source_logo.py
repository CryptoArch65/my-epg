#!/usr/bin/env python3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CHANNEL_ID = "MrezaZG.hr"
LOGO = "https://player.gledaj.hr/static/media/img/channels/dark/medium/273.png"

path = Path(sys.argv[1] if len(sys.argv) > 1 else "guide.xml")
tree = ET.parse(path)
root = tree.getroot()
channel = next((c for c in root.findall("channel") if c.get("id") == CHANNEL_ID), None)
if channel is None:
    raise SystemExit("MrezaZG.hr channel missing")
for icon in list(channel.findall("icon")):
    channel.remove(icon)
ET.SubElement(channel, "icon", {"src": LOGO})
ET.indent(tree, space="  ")
tree.write(path, encoding="utf-8", xml_declaration=True)
print(f"MrezaZG.hr logo={LOGO}")
