#!/usr/bin/env python3
"""Generate a realistic sample MacDive-style UDDF export for testing/demo.

This is *not* part of the calculator -- it just fabricates a handful of dives
with believable square / multilevel profiles (descent, bottom time, ascent and
a safety stop) so the calculator can be exercised without real data.
"""

import os
import random
from datetime import datetime, timedelta


def profile(max_depth, bottom_min, safety_stop=True, descent_rate=18.0,
            ascent_rate=9.0, sample_step=20):
    """Return a list of (time_s, depth_m) waypoints."""
    pts = [(0, 0.0)]
    t = 0
    # Descent.
    descent_time = max_depth / descent_rate * 60
    steps = max(1, int(descent_time / sample_step))
    for i in range(1, steps + 1):
        t += sample_step
        pts.append((t, max_depth * i / steps))
    # Bottom time (slight multilevel wobble).
    bottom_s = bottom_min * 60
    end = t + bottom_s
    while t < end:
        t += sample_step
        wobble = random.uniform(-1.5, 1.5)
        pts.append((t, max(0.0, max_depth + wobble)))
    # Ascent to 5 m.
    ascent_time = (max_depth - 5) / ascent_rate * 60
    steps = max(1, int(ascent_time / sample_step))
    d0 = pts[-1][1]
    for i in range(1, steps + 1):
        t += sample_step
        pts.append((t, d0 + (5 - d0) * i / steps))
    # Safety stop.
    if safety_stop:
        for _ in range(int(180 / sample_step)):
            t += sample_step
            pts.append((t, 5.0))
    # Final ascent to surface.
    for i in range(1, 4):
        t += sample_step
        pts.append((t, 5.0 * (3 - i) / 3))
    return pts


# Realistic, NDL-respecting recreational profiles spanning a range of
# decompression stress (depth m, bottom minutes, gas).
DIVES = [
    ("Blue Hole, Gozo", 38.0, 16, "nitrox32", 0.32),
    ("SS Thistlegorm", 30.0, 18, "air", 0.21),
    ("Manta Point", 16.0, 45, "air", 0.21),
    ("Richelieu Rock", 26.0, 24, "nitrox28", 0.28),
    ("Liberty Wreck", 28.0, 20, "air", 0.21),
    ("Shark Reef", 22.0, 30, "nitrox32", 0.32),
    ("Cathedral Cave", 40.0, 13, "nitrox28", 0.28),
    ("House Reef", 12.0, 55, "air", 0.21),
]


def build_uddf():
    random.seed(42)
    mixes = {
        "air": 0.21,
        "nitrox28": 0.28,
        "nitrox32": 0.32,
    }
    gas_xml = "".join(
        f"<mix id='{mid}'><name>{mid}</name><o2>{o2:.2f}</o2>"
        f"<n2>{1 - o2:.2f}</n2><he>0.0</he></mix>"
        for mid, o2 in mixes.items()
    )

    site_xml = "".join(
        f"<site id='site{i}'><name>{name}</name></site>"
        for i, (name, *_rest) in enumerate(DIVES)
    )

    start = datetime(2025, 3, 1, 9, 30)
    dives_xml = []
    for i, (name, depth, bt, gas, _o2) in enumerate(DIVES):
        dt = start + timedelta(days=i, hours=random.randint(0, 5))
        temp_k = 273.15 + random.uniform(18, 27)
        waypoints = []
        for t, d in profile(depth, bt):
            switch = f"<switchmix ref='{gas}'/>" if t == 0 else ""
            waypoints.append(
                f"<waypoint><depth>{d:.1f}</depth><divetime>{t}</divetime>"
                f"<temperature>{temp_k:.2f}</temperature>{switch}</waypoint>"
            )
        dives_xml.append(
            f"<dive id='dive{i + 1}'>"
            f"<informationbeforedive><datetime>{dt.isoformat()}</datetime>"
            f"<surfacepressure>101325</surfacepressure>"
            f"<link ref='site{i}'/></informationbeforedive>"
            f"<samples>{''.join(waypoints)}</samples>"
            f"</dive>"
        )

    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<uddf xmlns='http://www.streit.cc/uddf/3.2/' version='3.2.0'>"
        "<generator><name>make_sample.py</name></generator>"
        f"<gasdefinitions>{gas_xml}</gasdefinitions>"
        f"<divesite>{site_xml}</divesite>"
        "<profiledata><repetitiongroup>"
        f"{''.join(dives_xml)}"
        "</repetitiongroup></profiledata>"
        "</uddf>"
    )


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "macdive_sample.uddf")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(build_uddf())
    print(f"Wrote {out}")
