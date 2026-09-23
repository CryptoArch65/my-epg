import os
import xml.etree.ElementTree as ET

GUIDES_DIR = "guides"
OUTPUT_FILE = "guide.xml"

SOURCE_SUFFIXES = {
    "epg.telemach.ba": "telemach.ba",
    "maxtv.hrvatskitelekom.hr": "hrvatskitelekom.hr",
    "mtel.ba": "mtel.ba",
    "mts.rs": "mts.rs",
    "tvarenasport.com": "arenasport",
    "tvarenasport.hr": "arenasport.hr",
}


def normalize_name(name):
    name = name.strip()

    # XMLTV ID ne treba sadržavati razmake.
    # Razmake pretvaramo u '-'.
    name = " ".join(name.split())
    name = name.replace(" ", "-")

    return name


def process_file(filepath, source):
    tree = ET.parse(filepath)
    root = tree.getroot()

    suffix = SOURCE_SUFFIXES[source]

    id_map = {}

    # CHANNELS
    for channel in root.findall("channel"):
        old_id = channel.get("id")

        display_name = channel.findtext(
            "display-name",
            default=""
        ).strip()

        if not display_name or not old_id:
            continue

        new_id = f"{normalize_name(display_name)}.{suffix}"

        id_map[old_id] = new_id
        channel.set("id", new_id)

    # PROGRAMMES
    for programme in root.findall("programme"):
        old_channel = programme.get("channel")

        if old_channel in id_map:
            programme.set(
                "channel",
                id_map[old_channel]
            )

    return root


def main():
    combined_root = ET.Element(
        "tv",
        {
            "generator-info-name": "CryptoArch65/my-epg"
        }
    )

    total_channels = 0
    total_programmes = 0

    for source in SOURCE_SUFFIXES:
        filepath = os.path.join(
            GUIDES_DIR,
            f"{source}.xml"
        )

        if not os.path.exists(filepath):
            print(f"WARNING: Missing {filepath}")
            continue

        print(f"Processing {source}...")

        root = process_file(filepath, source)

        channels = root.findall("channel")
        programmes = root.findall("programme")

        for channel in channels:
            combined_root.append(channel)

        for programme in programmes:
            combined_root.append(programme)

        total_channels += len(channels)
        total_programmes += len(programmes)

        print(
            f"  Channels: {len(channels)}"
        )
        print(
            f"  Programmes: {len(programmes)}"
        )

    tree = ET.ElementTree(combined_root)

    ET.indent(tree, space="  ")

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True
    )

    print()
    print("===================================")
    print("EPG normalization completed")
    print(f"Channels:   {total_channels}")
    print(f"Programmes: {total_programmes}")
    print(f"Output:     {OUTPUT_FILE}")
    print("===================================")


if __name__ == "__main__":
    main()
