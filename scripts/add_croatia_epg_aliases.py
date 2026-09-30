#!/usr/bin/env python3
"""Add Croatia playlist aliases while safely replacing existing logo-only placeholders."""
import copy
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main(guide_path: Path, aliases_path: Path):
    with aliases_path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["playlist_tvg_id", "guide_id", "display_name"]:
            raise ValueError("Unexpected Croatia alias CSV header")
        aliases = list(reader)

    tree = ET.parse(guide_path)
    root = tree.getroot()
    if root.tag != "tv":
        raise ValueError("Expected XMLTV <tv> root")

    def channel_map():
        return {node.get("id"): node for node in root.findall("channel")}

    added = replaced = 0
    for row in aliases:
        alias = row["playlist_tvg_id"].strip()
        target = row["guide_id"].strip()
        display_name = row["display_name"].strip()
        if not alias or not target or not display_name:
            raise ValueError("Incomplete Croatia alias row")
        if alias == target:
            continue

        channels = channel_map()
        target_node = channels.get(target)
        if target_node is None:
            raise ValueError(f"Missing Croatia alias target: {target}")

        existing_alias = channels.get(alias)
        preserved_icon = None
        if existing_alias is not None:
            icon = existing_alias.find("icon")
            if icon is not None and icon.get("src"):
                preserved_icon = icon.get("src")
            root.remove(existing_alias)
            for programme in list(root.findall("programme")):
                if programme.get("channel") == alias:
                    root.remove(programme)
            replaced += 1
        else:
            added += 1

        alias_node = copy.deepcopy(target_node)
        alias_node.set("id", alias)
        for name in list(alias_node.findall("display-name")):
            alias_node.remove(name)
        name = ET.Element("display-name")
        name.text = display_name
        alias_node.insert(0, name)
        if preserved_icon:
            for icon in list(alias_node.findall("icon")):
                alias_node.remove(icon)
            alias_node.append(ET.Element("icon", {"src": preserved_icon}))

        nodes = list(root)
        first_programme = next((i for i, node in enumerate(nodes) if node.tag == "programme"), len(nodes))
        root.insert(first_programme, alias_node)

        target_programmes = [p for p in root.findall("programme") if p.get("channel") == target]
        for programme in target_programmes:
            duplicate = copy.deepcopy(programme)
            duplicate.set("channel", alias)
            root.append(duplicate)

    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(f"Croatia aliases: {added} added; {replaced} existing placeholders/aliases replaced")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: add_croatia_epg_aliases.py guide.xml aliases.csv")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
