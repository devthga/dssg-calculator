"""Compute the DAN Surface Supersaturation Gradient (DSSG) for a dive.

Methodology (per Marroni et al., Int. Maritime Health, 2026 -- DAN DSL 2024)
---------------------------------------------------------------------------
1. A Buhlmann ZH-L16C tissue model is initialised assuming the diver was
   saturated breathing air at the surface before the dive.
2. The recorded profile is normalised so the moment of surfacing is
   unambiguous: trailing samples shallower than or equal to 0.5 m (with no
   subsequent descent to >= 1 m) are collapsed into a single 0 m data point,
   preserving the sampling interval. (Most dive computers stop logging at
   0.5-1 m rather than exactly 0 m.)
3. The model is integrated segment-by-segment through that profile, using the
   breathing gas in effect at each waypoint (N2 and He).
4. At surfacing the supersaturation gradient of each compartment is
   ``tissue_tension - surface_pressure``.
5. The DSSG is the gradient of the *leading compartment* -- the one with the
   highest critical ratio at surfacing. Because the ambient (surface) pressure
   is identical for every compartment at that instant, the highest-ratio
   compartment is also the highest-tension / largest-gradient one, so the DSSG
   is ``max`` of the per-compartment surface gradients.

The DSSG is expressed in bar/ata (the paper's unit; mean 0.71, range
0.25-1.40). It is also available in metres of sea water (1 bar == 10 msw).
"""

from __future__ import annotations

from dataclasses import dataclass

from .buhlmann import MSW_PER_BAR, N_COMPARTMENTS, N2_HALFTIMES, TissueModel
from .parser import AIR, Dive, GasMix, Sample

# Depth (m) at or below which trailing samples are treated as "at the surface".
SURFACING_DEPTH_THRESHOLD = 0.5


@dataclass
class DSSGResult:
    """Outcome of a DSSG calculation for a single dive."""

    surface_gradients: list[float]          # per-compartment, bar
    compartment_tensions: list[float]       # per-compartment total tension, bar
    dssg_bar: float                         # leading-compartment gradient (bar/ata)
    leading_compartment: int                # 1-based compartment index (DSSG_COMPRT)
    gradient_track: list[tuple[float, float]]  # (time_s, max gradient bar) over dive

    @property
    def dssg_msw(self) -> float:
        return self.dssg_bar * MSW_PER_BAR


def _gas_for_ref(dive: Dive, ref: str | None) -> GasMix:
    if ref and ref in dive.gas_mixes:
        return dive.gas_mixes[ref]
    return AIR


def normalise_surfacing(samples: list[Sample]) -> list[Sample]:
    """Apply the DAN surfacing-correction rule to a profile.

    Trailing samples whose depth is <= 0.5 m -- with no later descent to
    >= 1 m -- are replaced by a single 0 m data point one sampling interval
    after the last deeper sample, so the DSSG is read at a consistent
    "surface" moment regardless of how a given dive computer stops logging.
    """
    if len(samples) < 2:
        return samples

    # Find the start of the trailing run of shallow (<= threshold) samples.
    cut = len(samples)
    while cut > 0 and samples[cut - 1].depth_m <= SURFACING_DEPTH_THRESHOLD:
        cut -= 1

    if cut == len(samples):
        return samples  # already ends deeper than the threshold; nothing to do
    if cut == 0:
        return samples  # whole dive is shallow; leave it untouched

    interval = _sampling_interval(samples)
    surface_time = samples[cut - 1].time_s + interval
    kept = samples[:cut]
    kept.append(Sample(time_s=surface_time, depth_m=0.0,
                       mix_ref=samples[cut].mix_ref))
    return kept


def _sampling_interval(samples: list[Sample]) -> float:
    diffs = [b.time_s - a.time_s for a, b in zip(samples, samples[1:])
             if b.time_s > a.time_s]
    if not diffs:
        return 1.0
    diffs.sort()
    return diffs[len(diffs) // 2]  # median interval


def compute_dssg(dive: Dive) -> DSSGResult:
    """Run the tissue model over ``dive`` and return its DSSG."""
    model = TissueModel(surface_pressure=dive.surface_pressure)

    samples = normalise_surfacing(dive.samples)

    # Establish the starting gas: the first explicit switch, else the first
    # defined mix, else air.
    current_gas = AIR
    for s in samples:
        if s.mix_ref:
            current_gas = _gas_for_ref(dive, s.mix_ref)
            break
    else:
        if dive.gas_mixes:
            current_gas = next(iter(dive.gas_mixes.values()))

    # Track the worst supersaturation gradient relative to the *current*
    # ambient pressure across the dive, for visualisation.
    gradient_track: list[tuple[float, float]] = []

    prev = samples[0]
    if prev.mix_ref:
        current_gas = _gas_for_ref(dive, prev.mix_ref)
    gradient_track.append((prev.time_s, _max_ambient_gradient(model, prev.depth_m, dive.surface_pressure)))

    for sample in samples[1:]:
        if sample.mix_ref:
            current_gas = _gas_for_ref(dive, sample.mix_ref)
        model.step(
            depth_start=prev.depth_m,
            depth_end=sample.depth_m,
            seconds=sample.time_s - prev.time_s,
            fn2=current_gas.fn2,
            fhe=current_gas.fhe,
        )
        gradient_track.append(
            (sample.time_s, _max_ambient_gradient(model, sample.depth_m, dive.surface_pressure))
        )
        prev = sample

    # Robustness fallback: if (outside the DAN rule) the profile still ends
    # clearly submerged, bring the diver to the surface so the gradient is a
    # genuine *surface* supersaturation gradient.
    if prev.depth_m > SURFACING_DEPTH_THRESHOLD:
        ascent_time = prev.depth_m / MSW_PER_BAR * 60.0  # ~10 m/min
        model.step(prev.depth_m, 0.0, ascent_time, current_gas.fn2, current_gas.fhe)
        gradient_track.append(
            (prev.time_s + ascent_time, _max_ambient_gradient(model, 0.0, dive.surface_pressure))
        )

    gradients = model.surface_gradients()
    tensions = model.total_tensions()
    leading = max(range(N_COMPARTMENTS), key=lambda i: gradients[i])

    return DSSGResult(
        surface_gradients=gradients,
        compartment_tensions=tensions,
        dssg_bar=gradients[leading],
        leading_compartment=leading + 1,
        gradient_track=gradient_track,
    )


def _max_ambient_gradient(model: TissueModel, depth_m: float, surface_pressure: float) -> float:
    """Largest tissue tension minus *current* ambient pressure (bar)."""
    ambient = surface_pressure + depth_m / MSW_PER_BAR
    return max(t - ambient for t in model.total_tensions())


def compartment_halftime(index_one_based: int) -> float:
    return N2_HALFTIMES[index_one_based - 1]
