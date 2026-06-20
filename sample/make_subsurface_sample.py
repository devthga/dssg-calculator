#!/usr/bin/env python3
"""Generate a small Subsurface native-XML (.ssrf) sample for testing/demo.

Reuses the profile generator from ``make_sample`` and emits the Subsurface
``<divelog>`` format (depth/time samples, cylinders, dive sites).
"""

import os

from make_sample import DIVES, profile


def _mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d} min"


def build():
    sites = "".join(
        f"<site uuid='site{i}' name='{name}'/>"
        for i, (name, *_rest) in enumerate(DIVES)
    )

    dives_xml = []
    for i, (name, depth, bt, gas, o2) in enumerate(DIVES):
        samples = "".join(
            f"<sample time='{_mmss(t)}' depth='{d:.1f} m' temp='26.0 C'/>"
            for t, d in profile(depth, bt)
        )
        date = f"2025-04-{i + 1:02d}"
        dives_xml.append(
            f"<dive number='{i + 1}' date='{date}' time='10:00:00' "
            f"divesiteid='site{i}'>"
            f"<cylinder size='11.1 l' o2='{round(o2 * 100)}.0%' he='0.0%'/>"
            f"<divecomputer model='Subsurface sample'>{samples}</divecomputer>"
            f"</dive>"
        )

    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<divelog program='subsurface' version='3'>"
        f"<divesites>{sites}</divesites>"
        f"<dives>{''.join(dives_xml)}</dives>"
        "</divelog>"
    )


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "subsurface_sample.ssrf")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(build())
    print(f"Wrote {out}")
