"""Compute the DAN Surface Supersaturation Gradient (DSSG) for a dive.

Methodology
-----------
1. A Buhlmann ZH-L16 tissue model is initialised assuming the diver was
   saturated breathing air at the surface before the dive.
2. The model is integrated segment-by-segment through the recorded depth/time
   profile, using the breathing gas in effect at each waypoint.
3. When the diver reaches the surface the *surface supersaturation gradient*
   of each compartment is ``tissue_tension - surface_pressure``.
4. The DSSG reported for the dive is the largest gradient across all
   compartments (the controlling / leading compartment) -- the peak
   decompression stress carried to the surface.

The gradient is reported both in bar and in metres of sea water (1 bar == 10
msw by the diving convention).
"""

from __future__ import annotations

from dataclasses import dataclass

from .buhlmann import MSW_PER_BAR, N_COMPARTMENTS, N2_HALFTIMES, TissueModel
from .parser import AIR, Dive, GasMix


@dataclass
class DSSGResult:
    """Outcome of a DSSG calculation for a single dive."""

    surface_gradients: list[float]          # per-compartment, bar
    compartment_tensions: list[float]       # per-compartment total tension, bar
    dssg_bar: float                         # controlling-compartment gradient
    leading_compartment: int                # 1-based compartment index
    gradient_track: list[tuple[float, float]]  # (time_s, max gradient bar) over dive

    @property
    def dssg_msw(self) -> float:
        return self.dssg_bar * MSW_PER_BAR


def _gas_for_ref(dive: Dive, ref: str | None) -> GasMix:
    if ref and ref in dive.gas_mixes:
        return dive.gas_mixes[ref]
    return AIR


def compute_dssg(dive: Dive) -> DSSGResult:
    """Run the tissue model over ``dive`` and return its DSSG."""
    model = TissueModel(surface_pressure=dive.surface_pressure)

    samples = dive.samples
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

    # If the profile does not end at the surface, bring the diver up so the
    # gradient is genuinely a *surface* supersaturation gradient.
    if prev.depth_m > 0.1:
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
