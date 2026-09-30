#!/usr/bin/env python3
"""Merge one XMLTV file into another, replacing duplicate channel IDs and their programmes."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main(base_path: Path, extra_path: Path, output_path: Path):
    base_tree = ET.parse(base_path)
    extra_tree = ET.parse(extra_path)
    base = base_tree.getroot()
    extra = extra_tree.getroot()
    if base.tag != "tv" or extra.tag != "tv":
        raise ValueError("Expected XMLTV <tv> roots")

    extra_ids = {node.get("id") for node in extra.findall("channel")}
    extra_ids.discard(None)
    if not extra_ids:
        raise ValueError("Extra XMLTV contains no channels")

    for node in list(base.findall("channel")):
        if node.get("id") in extra_ids:
            base.remove(node)
    for node in list(base.findall("programme")):
        if node.get("channel") in extra_ids:
            base.remove(node)

    first_programme = next((i for i, node in enumerate(list(base)) if node.tag == "programme"), len(base))
    for channel in extra.findall("channel"):
        base.insert(first_programme, channel)
        first_programme += 1
    for programme in extra.findall("programme"):
        base.append(programme)

    base_tree.write(output_path, encoding="utf-8", xml_declaration=True)
    print(f"Merged {len(extra_ids)} XMLTV channel(s): {', '.join(sorted(extra_ids))}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: merge_xmltv.py BASE.xml EXTRA.xml OUTPUT.xml")
    main(*(Path(value) for value in sys.argv[1:]))
