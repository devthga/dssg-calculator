"""Parsers for dive-log exports (UDDF and Subsurface native XML).

The DSSG calculation needs the full depth/time sample profile and the breathing
gas for every dive.  Several apps can export that:

* **MacDive**, and many others, via **UDDF** (Universal Dive Data Format).
* **Subsurface** via its native XML (``<divelog>``) or via UDDF.

Other tools (Shearwater, Suunto DM, DivingLog, Garmin Dive, etc.) that can
export UDDF are handled by the UDDF parser.  Files without a per-sample profile
(most summary-only CSV exports) cannot be analysed and are rejected.

XML is parsed with DTD/entity declarations disabled, which prevents
"billion laughs" entity-expansion denial-of-service from untrusted uploads.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import xml.parsers.expat as expat
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import Optional

from .buhlmann import FN2_AIR, STANDARD_SURFACE_PRESSURE

# Hard cap on input size (bytes) to bound memory/CPU on untrusted uploads.
MAX_INPUT_BYTES = 25 * 1024 * 1024


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
    """Return an element's tag without its XML namespace or prefix."""
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _strip_namespaces(root: ET.Element) -> ET.Element:
    for el in root.iter():
        el.tag = _localname(el.tag)
        el.attrib = {_localname(k): v for k, v in el.attrib.items()}
    return root


def safe_xml_root(path: str) -> ET.Element:
    """Parse an XML file into a namespace-stripped element tree, safely.

    DTD/DOCTYPE declarations are rejected, which blocks internal entity
    expansion ("billion laughs") attacks. External entities are not resolved
    by the underlying expat parser, so XXE is not possible either.
    """
    with open(path, "rb") as fh:
        data = fh.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError(
            f"input file exceeds the {MAX_INPUT_BYTES // (1024 * 1024)} MB limit")

    parser = expat.ParserCreate()

    def _forbid_dtd(*_args):
        raise ValueError("XML DTD/DOCTYPE declarations are not allowed")

    parser.StartDoctypeDeclHandler = _forbid_dtd
    builder = ET.TreeBuilder()
    parser.StartElementHandler = lambda tag, attrs: builder.start(tag, attrs)
    parser.EndElementHandler = lambda tag: builder.end(tag)
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        raise ValueError(f"invalid XML: {exc}") from exc
    return _strip_namespaces(builder.close())


def _find_text(el: ET.Element, tag: str) -> Optional[str]:
    child = el.find(tag)
    if child is not None and child.text is not None:
        return child.text.strip()
    return None


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    # Reject inf/nan so crafted profiles cannot poison the tissue model.
    return result if isfinite(result) else None


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
    return _parse_uddf_root(safe_xml_root(path))


def _parse_uddf_root(root: ET.Element) -> list[Dive]:
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


# --------------------------------------------------------------------------- #
# Subsurface native XML (<divelog>)
# --------------------------------------------------------------------------- #

def _ss_value(text: Optional[str]) -> Optional[float]:
    """Parse a Subsurface "value unit" string, e.g. '18.3 m' -> 18.3."""
    if not text:
        return None
    return _to_float(text.strip().split()[0])


def _ss_duration(text: Optional[str]) -> Optional[float]:
    """Parse a Subsurface time, e.g. '4:20 min' or '1:02:03' -> seconds."""
    if not text:
        return None
    token = text.strip().split()[0]
    seconds = 0.0
    for part in token.split(":"):
        value = _to_float(part)
        if value is None:
            return None
        seconds = seconds * 60.0 + value
    return seconds


def _ss_percent(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    return _to_float(text.replace("%", "").strip())


def _ss_gasmixes(dive_el: ET.Element) -> dict[str, GasMix]:
    mixes: dict[str, GasMix] = {}
    for idx, cyl in enumerate(dive_el.findall("cylinder")):
        o2 = _ss_percent(cyl.attrib.get("o2"))
        he = _ss_percent(cyl.attrib.get("he")) or 0.0
        fo2 = (o2 / 100.0) if o2 is not None else 0.21
        fhe = he / 100.0
        name = "Air" if abs(fo2 - 0.21) < 1e-6 and fhe == 0 else (
            f"EAN{round(fo2 * 100)}" if fhe == 0 else
            f"Tx{round(fo2 * 100)}/{round(fhe * 100)}")
        mixes[f"cyl{idx}"] = GasMix(mix_id=f"cyl{idx}", name=name, fo2=fo2, fhe=fhe)
    if not mixes:
        mixes["cyl0"] = AIR
    return mixes


def _ss_samples(dc_el: ET.Element) -> list[Sample]:
    # Gas-switch events: (time_s, cylinder index).
    switches: list[tuple[float, int]] = []
    for ev in dc_el.findall("event"):
        if ev.attrib.get("name") == "gaschange":
            t = _ss_duration(ev.attrib.get("time")) or 0.0
            try:
                cyl = int(ev.attrib.get("cylinder", "0"))
            except ValueError:
                cyl = 0
            switches.append((t, cyl))
    switches.sort()

    def active_cylinder(t: float) -> int:
        cyl = 0
        for sw_t, sw_cyl in switches:
            if sw_t <= t:
                cyl = sw_cyl
            else:
                break
        return cyl

    samples: list[Sample] = []
    for s in dc_el.findall("sample"):
        t = _ss_duration(s.attrib.get("time"))
        depth = _ss_value(s.attrib.get("depth"))
        if t is None or depth is None:
            continue
        temp_c = _ss_value(s.attrib.get("temp"))
        temp_k = temp_c + 273.15 if temp_c is not None else None
        samples.append(Sample(time_s=t, depth_m=depth,
                              mix_ref=f"cyl{active_cylinder(t)}",
                              temperature_k=temp_k))
    samples.sort(key=lambda x: x.time_s)
    return samples


def parse_subsurface(path: str) -> list[Dive]:
    """Parse a Subsurface native XML (.ssrf/.xml) export."""
    return _parse_subsurface_root(safe_xml_root(path))


def _parse_subsurface_root(root: ET.Element) -> list[Dive]:
    # Dive-site uuid -> name (Subsurface >= 4.7 keeps sites separately).
    sites: dict[str, str] = {}
    for site in root.iter("site"):
        uuid = site.attrib.get("uuid")
        name = site.attrib.get("name")
        if uuid and name:
            sites[uuid] = name

    dives: list[Dive] = []
    number = 0
    for dive_el in root.iter("dive"):
        dc = dive_el.find("divecomputer")
        samples = _ss_samples(dc) if dc is not None else []
        if not samples:
            continue
        number += 1

        date = dive_el.attrib.get("date", "")
        time = dive_el.attrib.get("time", "")
        dt = _parse_datetime(f"{date}T{time}" if date and time else date or None)

        location = None
        site_ref = dive_el.attrib.get("divesiteid")
        if site_ref and site_ref in sites:
            location = sites[site_ref]
        elif _find_text(dive_el, "location"):
            location = _find_text(dive_el, "location")

        dives.append(
            Dive(
                number=number,
                dive_id=dive_el.attrib.get("number") or f"dive-{number}",
                datetime=dt,
                location=location,
                samples=samples,
                surface_pressure=STANDARD_SURFACE_PRESSURE,
                gas_mixes=_ss_gasmixes(dive_el),
            )
        )
    return dives


# --------------------------------------------------------------------------- #
# Format detection / dispatch
# --------------------------------------------------------------------------- #

SUPPORTED_FORMATS = (
    "UDDF (MacDive, Subsurface, Shearwater, Suunto DM, DivingLog, Garmin, …)",
    "Subsurface native XML (.ssrf / .xml)",
)


def parse_dive_log(path: str) -> tuple[str, list[Dive]]:
    """Detect the export format and parse it.

    Returns ``(format_name, dives)``. Raises ``ValueError`` if the format is
    unsupported or contains no analysable dive profiles.
    """
    root = safe_xml_root(path)
    tag = root.tag.lower()

    if tag == "uddf":
        return "UDDF", _parse_uddf_root(root)
    if tag == "divelog":
        return "Subsurface", _parse_subsurface_root(root)

    # Unknown root: try UDDF heuristically (some exporters omit/rename it).
    if root.find(".//waypoint") is not None:
        return "UDDF", _parse_uddf_root(root)
    if root.find(".//sample") is not None:
        return "Subsurface", _parse_subsurface_root(root)

    raise ValueError(
        "unrecognised dive-log format. Supported: " + "; ".join(SUPPORTED_FORMATS))
