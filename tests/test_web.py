"""Tests for multi-format ingestion, XML hardening and the FastAPI web app."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dssg.parser import parse_dive_log, safe_xml_root

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sample")
UDDF = os.path.join(SAMPLE_DIR, "macdive_sample.uddf")
SSRF = os.path.join(SAMPLE_DIR, "subsurface_sample.ssrf")

BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE uddf [
  <!ENTITY a "aaaaaaaaaa">
  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
  <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">
]>
<uddf><name>&c;</name></uddf>"""


class FormatTests(unittest.TestCase):
    def test_detect_uddf(self):
        if not os.path.exists(UDDF):
            self.skipTest("uddf sample not generated")
        fmt, dives = parse_dive_log(UDDF)
        self.assertEqual(fmt, "UDDF")
        self.assertGreater(len(dives), 0)

    def test_detect_subsurface(self):
        if not os.path.exists(SSRF):
            self.skipTest("subsurface sample not generated")
        fmt, dives = parse_dive_log(SSRF)
        self.assertEqual(fmt, "Subsurface")
        self.assertGreater(len(dives), 0)
        self.assertGreater(len(dives[0].samples), 5)

    def test_subsurface_units_parsed(self):
        from dssg.parser import _ss_duration, _ss_percent, _ss_value
        self.assertAlmostEqual(_ss_value("18.3 m"), 18.3)
        self.assertEqual(_ss_duration("4:20 min"), 260.0)
        self.assertEqual(_ss_duration("1:02:03"), 3723.0)
        self.assertAlmostEqual(_ss_percent("32.0%"), 32.0)

    def test_unsupported_format_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
            fh.write("<somethingelse><a/></somethingelse>")
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                parse_dive_log(path)
        finally:
            os.unlink(path)


class XmlHardeningTests(unittest.TestCase):
    def test_billion_laughs_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".uddf", delete=False) as fh:
            fh.write(BILLION_LAUGHS)
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                safe_xml_root(path)
        finally:
            os.unlink(path)

    def test_oversize_rejected(self):
        from dssg.parser import MAX_INPUT_BYTES
        with tempfile.NamedTemporaryFile("wb", suffix=".uddf", delete=False) as fh:
            fh.write(b"<uddf>" + b" " * (MAX_INPUT_BYTES + 10) + b"</uddf>")
            path = fh.name
        try:
            with self.assertRaises(ValueError):
                safe_xml_root(path)
        finally:
            os.unlink(path)


class WebAppTests(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"fastapi/testclient unavailable: {exc}")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DSSG_DATA_DIR"] = self._tmp.name
        # Import after setting the data dir so the store uses the temp path.
        import importlib

        import dssg.web as web
        importlib.reload(web)
        self.web = web
        self.client = TestClient(web.app)

    def tearDown(self):
        self._tmp.cleanup()

    def test_landing_page(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("DSSG", r.text)

    def test_upload_analyse_and_browse(self):
        if not os.path.exists(UDDF):
            self.skipTest("uddf sample not generated")
        with open(UDDF, "rb") as fh:
            r = self.client.post(
                "/upload",
                files={"file": ("macdive_sample.uddf", fh.read(), "application/xml")},
                follow_redirects=False,
            )
        self.assertEqual(r.status_code, 303)
        loc = r.headers["location"]
        self.assertTrue(loc.startswith("/report/"))

        report = self.client.get(loc)
        self.assertEqual(report.status_code, 200)
        self.assertIn("DSSG", report.text)

        uid = loc.split("/")[2]
        stats = self.client.get(f"/report/{uid}/statistics.json")
        self.assertEqual(stats.status_code, 200)
        self.assertIn("dssg", stats.json())

        # The raw upload must be permanently retrievable.
        raw = self.client.get(f"/download/{uid}")
        self.assertEqual(raw.status_code, 200)

        # And it should appear in the API listing.
        listing = self.client.get("/api/analyses").json()
        self.assertTrue(any(e["id"] == uid for e in listing))

    def test_upload_billion_laughs_is_stored_but_not_analysed(self):
        r = self.client.post(
            "/upload",
            files={"file": ("evil.uddf", BILLION_LAUGHS, "application/xml")},
            follow_redirects=False,
        )
        # Stored, but analysis fails safely -> back to landing page with error.
        self.assertEqual(r.status_code, 200)
        self.assertIn("could not be analysed", r.text)

    def test_report_path_traversal_blocked(self):
        r = self.client.get("/report/" + "0" * 32 + "/../../index.json")
        self.assertIn(r.status_code, (404, 400))


if __name__ == "__main__":
    unittest.main(verbosity=2)
