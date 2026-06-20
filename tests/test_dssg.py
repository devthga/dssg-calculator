"""Unit tests for the DSSG calculator (stdlib unittest, no dependencies)."""

import math
import os
import sys
import unittest
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dssg.buhlmann import (STANDARD_SURFACE_PRESSURE, TissueModel,
                           WATER_VAPOUR_PRESSURE, FN2_AIR)
from dssg.calculator import compute_dssg
from dssg.parser import Dive, GasMix, Sample, parse_uddf


class TissueModelTests(unittest.TestCase):
    def test_initial_saturation(self):
        m = TissueModel()
        expected = (STANDARD_SURFACE_PRESSURE - WATER_VAPOUR_PRESSURE) * FN2_AIR
        for p in m.p_n2:
            self.assertAlmostEqual(p, expected, places=6)
        # Already saturated at surface -> gradient is small/negative.
        self.assertLessEqual(max(m.surface_gradients()), 0.0)

    def test_staying_at_surface_keeps_gradient_zero(self):
        m = TissueModel()
        m.step(0.0, 0.0, 3600, FN2_AIR, 0.0)  # one hour at the surface on air
        self.assertLess(max(m.surface_gradients()), 1e-6)

    def test_schreiner_constant_depth_matches_haldane(self):
        # At constant depth (rate=0) Schreiner must reduce to the Haldane
        # exponential equilibration toward the inspired pressure.
        m = TissueModel()
        depth, minutes = 30.0, 20.0
        m.step(depth, depth, minutes * 60, FN2_AIR, 0.0)

        amb = STANDARD_SURFACE_PRESSURE + depth / 10.0
        pi = (amb - WATER_VAPOUR_PRESSURE) * FN2_AIR
        p0 = (STANDARD_SURFACE_PRESSURE - WATER_VAPOUR_PRESSURE) * FN2_AIR
        # Compartment 1 (ZH-L16C: 4.0 min half-time) check:
        from dssg.buhlmann import N2_HALFTIMES
        ht = N2_HALFTIMES[0]
        self.assertEqual(ht, 4.0)
        k = math.log(2) / ht
        haldane = pi + (p0 - pi) * math.exp(-k * minutes)
        self.assertAlmostEqual(m.p_n2[0], haldane, places=6)

    def test_deeper_longer_increases_dssg(self):
        shallow = _square_dive(15.0, 20)
        deep = _square_dive(35.0, 40)
        self.assertGreater(compute_dssg(deep).dssg,
                           compute_dssg(shallow).dssg)

    def test_nitrox_reduces_dssg_vs_air(self):
        air = _square_dive(30.0, 30, fo2=0.21)
        nitrox = _square_dive(30.0, 30, fo2=0.32)
        self.assertGreater(compute_dssg(air).dssg,
                           compute_dssg(nitrox).dssg)

    def test_dssg_positive_for_real_dive(self):
        res = compute_dssg(_square_dive(30.0, 30))
        self.assertGreater(res.dssg, 0.0)
        self.assertTrue(1 <= res.leading_compartment <= 16)

    def test_dssg_is_gradient_factor(self):
        # The DSSG is a gradient factor: 1.0 == at the ZH-L16C M-value. A no-
        # stop recreational profile should sit below ~1.4 GF; a benign one
        # should be modest.
        res = compute_dssg(_square_dive(18.0, 40))
        self.assertGreater(res.dssg, 0.25)
        self.assertLessEqual(res.dssg, 1.40)

    def test_gf_at_surface_saturation_is_zero(self):
        # Saturated on air at the surface => no supersaturation => GF ~ 0.
        from dssg.buhlmann import TissueModel
        gfs = TissueModel().gradient_factors()
        self.assertLessEqual(max(gfs), 1e-6)


class SurfacingCorrectionTests(unittest.TestCase):
    def test_trailing_shallow_collapsed_to_surface(self):
        from dssg.calculator import normalise_surfacing
        from dssg.parser import Sample
        samples = [Sample(0, 0.0), Sample(60, 20.0), Sample(120, 20.0),
                   Sample(180, 0.4), Sample(200, 0.3), Sample(220, 0.2)]
        out = normalise_surfacing(samples)
        self.assertEqual(out[-1].depth_m, 0.0)
        # the three trailing <=0.5 m samples collapse into one 0 m point
        self.assertEqual(len(out), 4)

    def test_profile_ending_at_half_meter_matches_zero(self):
        # A computer that stops at 0.5 m should give ~the same DSSG as one
        # that reaches 0 m, thanks to the surfacing correction.
        a = _square_dive(30.0, 30, last_depth=0.0)
        b = _square_dive(30.0, 30, last_depth=0.4)
        self.assertAlmostEqual(compute_dssg(a).dssg,
                               compute_dssg(b).dssg, places=2)


class RiskTests(unittest.TestCase):
    def test_band_thresholds(self):
        from dssg.risk import classify
        self.assertEqual(classify(0.5).label, "Very low")
        self.assertEqual(classify(0.75).label, "Moderate")
        self.assertEqual(classify(0.95).label, "High")
        self.assertEqual(classify(1.2).label, "Very high")

    def test_dcs_rate_monotonic(self):
        from dssg.risk import classify
        rates = [classify(x).dcs_rate_pct for x in (0.5, 0.65, 0.75, 0.85, 0.95, 1.1)]
        self.assertEqual(rates, sorted(rates))


class ParserTests(unittest.TestCase):
    def test_parse_sample_file(self):
        sample = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                              "sample", "macdive_sample.uddf")
        if not os.path.exists(sample):
            self.skipTest("sample file not generated")
        dives = parse_uddf(sample)
        self.assertGreater(len(dives), 0)
        d = dives[0]
        self.assertGreater(len(d.samples), 5)
        self.assertGreater(d.max_depth, 0)
        self.assertIsNotNone(d.location)


class _TagBalanceChecker(HTMLParser):
    """Verify start/end tags are balanced and properly nested."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unbalanced </{tag}>; stack={self.stack[-3:]}")
        else:
            self.stack.pop()


class HtmlTests(unittest.TestCase):
    def test_generated_html_is_well_formed(self):
        from dssg.report import render_dive, render_index
        from dssg.statistics_report import build_statistics, summarise_dive

        dive = _square_dive(30.0, 30)
        res = compute_dssg(dive)
        summ = summarise_dive(dive, res)
        stats = build_statistics([summ])

        for doc in (render_index([summ], stats), render_dive(dive, res, summ)):
            checker = _TagBalanceChecker()
            checker.feed(doc)
            self.assertEqual(checker.errors, [], f"tag errors: {checker.errors}")
            self.assertEqual(checker.stack, [], f"unclosed tags: {checker.stack}")
            self.assertIn("DSSG", doc)


def _square_dive(max_depth, bottom_min, fo2=0.21, last_depth=0.0):
    """Build a simple square-profile dive in memory."""
    step = 20
    samples = [Sample(time_s=0, depth_m=0.0, mix_ref="m")]
    t = 0
    # descent at 18 m/min
    while samples[-1].depth_m < max_depth:
        t += step
        samples.append(Sample(t, min(max_depth, samples[-1].depth_m + 18 * step / 60)))
    # bottom
    end = t + bottom_min * 60
    while t < end:
        t += step
        samples.append(Sample(t, max_depth))
    # ascent at 9 m/min to (near) surface
    while samples[-1].depth_m > last_depth:
        t += step
        samples.append(Sample(t, max(last_depth, samples[-1].depth_m - 9 * step / 60)))
    return Dive(
        number=1, dive_id="t", datetime=None, location="Test",
        samples=samples,
        gas_mixes={"m": GasMix("m", "mix", fo2=fo2, fhe=0.0)},
    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
