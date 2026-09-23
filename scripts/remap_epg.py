import json
import re
import sys

guide_file = sys.argv[1]
mapping_file = sys.argv[2]

with open(mapping_file, "r", encoding="utf-8") as f:
    mappings = json.load(f)

with open(guide_file, "r", encoding="utf-8") as f:
    xml = f.read()

for old_id, new_id in mappings.items():
    # <channel id="OLD">
    xml = re.sub(
        rf'(<channel\s+id="){re.escape(old_id)}(")',
        rf'\g<1>{new_id}\g<2>',
        xml
    )

    # channel="OLD" inside <programme>
    xml = re.sub(
        rf'(\schannel="){re.escape(old_id)}(")',
        rf'\g<1>{new_id}\g<2>',
        xml
    )

with open(guide_file, "w", encoding="utf-8") as f:
    f.write(xml)

print("EPG mapping completed:")
for old_id, new_id in mappings.items():
    print(f"  {old_id} -> {new_id}")
