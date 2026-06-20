"""Parser for MacDive UDDF (Universal Dive Data Format) exports.

MacDive's *Export > UDDF* produces an XML document containing, among other
things, the full depth/time sample profile for every dive plus the gas mixes
used.  That profile is exactly what the DSSG calculation needs.

The parser is deliberately tolerant: UDDF documents in the wild vary in their
namespace, element ordering and which optional fields are present.  Missing
data falls back to sensible defaults (air, sea-level atmospheric pressure).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .buhlmann import FN2_AIR, STANDARD_SURFACE_PRESSURE


@dataclass
class GasMix:
    """A breathing-gas definition."""

    mix_id: str
    name: str
    fo2: float
    fhe: float

    @property
    def fn2(self) -> float:
        return max(0.0, 1.0 - self.fo2 - self.fhe)


# Air, used whenever a dive references no usable gas definition.
AIR = GasMix(mix_id="air", name="Air", fo2=0.21, fhe=0.0)


@dataclass
class Sample:
    """A single profile waypoint."""

    time_s: float
    depth_m: float
    mix_ref: Optional[str] = None
    temperature_k: Optional[float] = None


@dataclass
class Dive:
    """A single parsed dive."""

    number: int
    dive_id: str
    datetime: Optional[datetime]
    location: Optional[str]
    samples: list[Sample]
    surface_pressure: float = STANDARD_SURFACE_PRESSURE
    gas_mixes: dict[str, GasMix] = field(default_factory=dict)

    @property
    def max_depth(self) -> float:
        return max((s.depth_m for s in self.samples), default=0.0)

    @property
    def duration_s(self) -> float:
        if not self.samples:
            return 0.0
        return max(s.time_s for s in self.samples)

    @property
    def min_temp_c(self) -> Optional[float]:
        temps = [s.temperature_k for s in self.samples if s.temperature_k]
        if not temps:
            return None
        return min(temps) - 273.15


def _localname(tag: str) -> str:
    """Return an element's tag without its XML namespace."""
    return tag.rsplit("}", 1)[-1]


def _strip_namespaces(root: ET.Element) -> ET.Element:
    for el in root.iter():
        el.tag = _localname(el.tag)
        el.attrib = {_localname(k): v for k, v in el.attrib.items()}
    return root


def _find_text(el: ET.Element, tag: str) -> Optional[str]:
    child = el.find(tag)
    if child is not None and child.text is not None:
        return child.text.strip()
    return None


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_datetime(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    text = text.strip().replace("Z", "+00:00")
    for parser in (
        datetime.fromisoformat,
        lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%S"),
        lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
        lambda s: datetime.strptime(s, "%Y-%m-%d"),
    ):
        try:
            return parser(text)
        except (ValueError, TypeError):
            continue
    return None


def _parse_gas_definitions(root: ET.Element) -> dict[str, GasMix]:
    mixes: dict[str, GasMix] = {}
    for mix in root.iter("mix"):
        mix_id = mix.attrib.get("id") or _find_text(mix, "name") or f"mix{len(mixes)}"
        name = _find_text(mix, "name") or mix_id
        fo2 = _to_float(_find_text(mix, "o2"))
        fhe = _to_float(_find_text(mix, "he")) or 0.0
        if fo2 is None:
            fn2 = _to_float(_find_text(mix, "n2"))
            fo2 = (1.0 - fn2 - fhe) if fn2 is not None else 0.21
        mixes[mix_id] = GasMix(mix_id=mix_id, name=name, fo2=fo2, fhe=fhe)
    return mixes


def _parse_dive_sites(root: ET.Element) -> dict[str, str]:
    """Map dive-site ids to human-readable names."""
    sites: dict[str, str] = {}
    for site in root.iter("site"):
        site_id = site.attrib.get("id")
        if not site_id:
            continue
        name = _find_text(site, "name")
        if name:
            sites[site_id] = name
    return sites


def _parse_samples(dive_el: ET.Element) -> list[Sample]:
    samples: list[Sample] = []
    container = dive_el.find("samples")
    if container is None:
        return samples
    for wp in container.findall("waypoint"):
        time_s = _to_float(_find_text(wp, "divetime"))
        depth_m = _to_float(_find_text(wp, "depth"))
        if time_s is None or depth_m is None:
            continue
        mix_ref = None
        switch = wp.find("switchmix")
        if switch is not None:
            mix_ref = switch.attrib.get("ref")
        temp = _to_float(_find_text(wp, "temperature"))
        samples.append(
            Sample(time_s=time_s, depth_m=depth_m, mix_ref=mix_ref, temperature_k=temp)
        )
    samples.sort(key=lambda s: s.time_s)
    return samples


def _surface_pressure_for_dive(dive_el: ET.Element) -> float:
    """Read surface pressure (UDDF stores it in pascal) for the dive."""
    info = dive_el.find("informationbeforedive")
    if info is not None:
        pa = _to_float(_find_text(info, "surfacepressure"))
        if pa:
            # UDDF surfacepressure is in pascal.
            return pa / 100000.0
    return STANDARD_SURFACE_PRESSURE


def _dive_location(dive_el: ET.Element, sites: dict[str, str]) -> Optional[str]:
    info = dive_el.find("informationbeforedive")
    if info is None:
        return None
    link = info.find("link")
    if link is not None:
        ref = link.attrib.get("ref")
        if ref and ref in sites:
            return sites[ref]
    return None


def parse_uddf(path: str) -> list[Dive]:
    """Parse a UDDF file into a list of :class:`Dive` objects."""
    tree = ET.parse(path)
    root = _strip_namespaces(tree.getroot())

    global_mixes = _parse_gas_definitions(root)
    sites = _parse_dive_sites(root)

    dives: list[Dive] = []
    number = 0
    for dive_el in root.iter("dive"):
        number += 1
        dive_id = dive_el.attrib.get("id") or f"dive-{number}"

        info = dive_el.find("informationbeforedive")
        dt = _parse_datetime(_find_text(info, "datetime") if info is not None else None)

        samples = _parse_samples(dive_el)
        if not samples:
            # Without a profile the DSSG cannot be computed; skip the dive.
            number -= 1
            continue

        dives.append(
            Dive(
                number=number,
                dive_id=dive_id,
                datetime=dt,
                location=_dive_location(dive_el, sites),
                samples=samples,
                surface_pressure=_surface_pressure_for_dive(dive_el),
                gas_mixes=dict(global_mixes),
            )
        )

    return dives
