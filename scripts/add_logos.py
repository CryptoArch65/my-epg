import json
import urllib.request
import xml.etree.ElementTree as ET

GUIDE_FILE = "guide.xml"
LOGOS_URL = "https://iptv-org.github.io/api/logos.json"


def normalize(text):
    return " ".join(text.lower().split())


def load_logos():
    print("Downloading iptv-org logos.json...")

    with urllib.request.urlopen(LOGOS_URL, timeout=60) as response:
        data = json.load(response)

    logos = {}

    for item in data:
        if not item.get("in_use"):
            continue

        channel = item.get("channel")
        url = item.get("url")

        if not channel or not url:
            continue

        # Prefer SVG/PNG and larger logos
        score = 0

        if item.get("format") == "SVG":
            score += 100
        elif item.get("format") == "PNG":
            score += 90

        score += min(item.get("width", 0), 2000) / 1000

        if channel not in logos or score > logos[channel]["score"]:
            logos[channel] = {
                "url": url,
                "score": score
            }

    print(f"Loaded {len(logos)} active logos")

    return logos


def load_channels():
    tree = ET.parse(GUIDE_FILE)
    root = tree.getroot()

    channels = []

    for channel in root.findall("channel"):
        channel_id = channel.get("id")
        display_name = channel.findtext("display-name", "").strip()

        if channel_id and display_name:
            channels.append({
                "element": channel,
                "id": channel_id,
                "name": display_name
            })

    return tree, root, channels


def find_logo(channel_name, logos):
    target = normalize(channel_name)

    # Exact channel-name match
    for logo_id, logo in logos.items():

        # iptv-org IDs usually end with country code,
        # so compare the main part too.
        base = logo_id.rsplit(".", 1)[0]

        if normalize(base) == target:
            return logo["url"]

    return None


def main():

    logos = load_logos()

    tree, root, channels = load_channels()

    found = 0
    missing = 0

    for item in channels:

        channel = item["element"]
        name = item["name"]

        logo_url = find_logo(name, logos)

        # Remove any source-specific logo
        old_icon = channel.find("icon")

        if old_icon is not None:
            channel.remove(old_icon)

        if logo_url:
            ET.SubElement(
                channel,
                "icon",
                {"src": logo_url}
            )

            found += 1
            print(f"LOGO: {name} -> {logo_url}")

        else:
            missing += 1
            print(f"NO LOGO: {name}")

    ET.indent(tree, space="  ")

    tree.write(
        GUIDE_FILE,
        encoding="utf-8",
        xml_declaration=True
    )

    print()
    print("===================================")
    print("Logo processing completed")
    print(f"Logos found: {found}")
    print(f"Logos missing: {missing}")
    print("===================================")


if __name__ == "__main__":
    main()
