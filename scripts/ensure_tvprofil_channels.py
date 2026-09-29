#!/usr/bin/env python3
"""Ensure every configured TVProfil channel exists as an XMLTV <channel> node."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main(guide_path: str, config_path: str) -> None:
    channels = json.loads(Path(config_path).read_text(encoding="utf-8"))
    tree = ET.parse(guide_path)
    root = tree.getroot()
    existing = {node.get("id") for node in root.findall("channel")}

    first_programme = root.find("programme")
    insert_at = list(root).index(first_programme) if first_programme is not None else len(root)
    added = 0

    for channel in channels:
        xmltv_id = channel["xmltv_id"]
        if xmltv_id in existing:
            continue
        node = ET.Element("channel", {"id": xmltv_id})
        ET.SubElement(node, "display-name", {"lang": "hr"}).text = channel.get("display_name") or xmltv_id
        root.insert(insert_at, node)
        insert_at += 1
        existing.add(xmltv_id)
        added += 1

    ET.indent(tree, space="  ")
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(f"TVProfil channel nodes added: {added}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: ensure_tvprofil_channels.py guide.xml config/tvprofil_channels.json")
    main(sys.argv[1], sys.argv[2])
