import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from scripts.validate_guide import main


class TestValidateGuide(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_file = Path(self.temp_dir.name) / "channels.xml"
        self.guide_file = Path(self.temp_dir.name) / "guide.xml"

        # Create basic channels config with 1 channel
        channels_xml = """<?xml version="1.0" encoding="utf-8"?>
<channels>
  <channel site="test.site" site_id="1" lang="hr" xmltv_id="Test.hr">Test Channel</channel>
</channels>
"""
        self.config_file.write_text(channels_xml, encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_guide(self, programmes):
        guide_xml = """<?xml version="1.0" encoding="utf-8"?>
<tv>
  <channel id="Test.hr">
    <display-name>Test Channel</display-name>
  </channel>
"""
        for p in programmes:
            guide_xml += f"""  <programme start="{p['start']}" stop="{p['stop']}" channel="Test.hr">
    <title>{p.get('title', 'Test Program')}</title>
  </programme>
"""
        guide_xml += "</tv>\n"
        self.guide_file.write_text(guide_xml, encoding="utf-8")

    def test_stop_not_after_start(self):
        self._write_guide([
            {"start": "20261001120000 +0000", "stop": "20261001110000 +0000", "title": "Prog 1"}
        ])
        with self.assertRaises(ValueError) as ctx:
            main(str(self.config_file), str(self.guide_file), now=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc))
        self.assertIn("stop time is not after start time", str(ctx.exception))
        self.assertIn("Test.hr", str(ctx.exception))
        self.assertIn("Prog 1", str(ctx.exception))

    def test_stop_equals_start(self):
        self._write_guide([
            {"start": "20261001120000 +0000", "stop": "20261001120000 +0000", "title": "Zero Length"}
        ])
        with self.assertRaises(ValueError) as ctx:
            main(str(self.config_file), str(self.guide_file), now=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc))
        self.assertIn("stop time is not after start time", str(ctx.exception))

    def test_invalid_start_timestamp(self):
        self._write_guide([
            {"start": "invalid-timestamp", "stop": "20261001120000 +0000", "title": "Bad Start"}
        ])
        with self.assertRaises(ValueError) as ctx:
            main(str(self.config_file), str(self.guide_file), now=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc))
        self.assertIn("fails to parse with '%Y%m%d%H%M%S %z'", str(ctx.exception))
        self.assertIn("Test.hr", str(ctx.exception))

    def test_invalid_stop_timestamp(self):
        self._write_guide([
            {"start": "20261001120000 +0000", "stop": "invalid-timestamp", "title": "Bad Stop"}
        ])
        with self.assertRaises(ValueError) as ctx:
            main(str(self.config_file), str(self.guide_file), now=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc))
        self.assertIn("fails to parse with '%Y%m%d%H%M%S %z'", str(ctx.exception))
        self.assertIn("Test.hr", str(ctx.exception))

    def test_overlapping_programmes(self):
        self._write_guide([
            {"start": "20261001120000 +0000", "stop": "20261001130000 +0000", "title": "Prog 1"},
            {"start": "20261001123000 +0000", "stop": "20261001133000 +0000", "title": "Prog 2"},
        ])
        with self.assertRaises(ValueError) as ctx:
            main(str(self.config_file), str(self.guide_file), now=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc))
        self.assertIn("Overlapping programmes on channel 'Test.hr'", str(ctx.exception))
        self.assertIn("Prog 1", str(ctx.exception))
        self.assertIn("Prog 2", str(ctx.exception))

    def test_all_programmes_in_past(self):
        # 501 programmes all in 2020, with 'now' in 2026
        # Generate 501 valid non-overlapping programmes in the past to satisfy the >= 500 threshold
        # and test the future programmes check
        progs = []
        for i in range(501):
            day = 1 + (i // 24)
            hour = i % 24
            next_hour = (hour + 1) % 24
            next_day = day + (1 if hour == 23 else 0)
            start = f"202001{day:02d}{hour:02d}0000 +0000"
            stop = f"202001{next_day:02d}{next_hour:02d}0000 +0000"
            progs.append({"start": start, "stop": stop, "title": f"Past Prog {i}"})

        self._write_guide(progs)
        with self.assertRaises(ValueError) as ctx:
            main(str(self.config_file), str(self.guide_file), now=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc))
        self.assertIn("Guide contains no future programmes", str(ctx.exception))

    def test_valid_programmes_with_future(self):
        # 501 programmes, at least some extending into the future
        progs = []
        for i in range(501):
            day = 1 + (i // 24)
            hour = i % 24
            next_hour = (hour + 1) % 24
            next_day = day + (1 if hour == 23 else 0)
            start = f"202610{day:02d}{hour:02d}0000 +0000"
            stop = f"202610{next_day:02d}{next_hour:02d}0000 +0000"
            progs.append({"start": start, "stop": stop, "title": f"Future Prog {i}"})

        self._write_guide(progs)
        # Should succeed with now set before the programmes
        main(str(self.config_file), str(self.guide_file), now=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
