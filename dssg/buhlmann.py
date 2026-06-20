"""Buhlmann ZH-L16 inert-gas tissue model.

The model is used to track the partial pressure of the inert gases (nitrogen
and helium) in 16 theoretical tissue compartments while a diver moves through
a depth/time profile.  At the moment the diver reaches the surface the
*supersaturation gradient* of each compartment is the amount by which its
dissolved inert-gas tension exceeds the ambient (surface) pressure.

The half-times integrate the gas tensions; the ZH-L16C a/b coefficients give
each compartment's M-value, which is needed to express the supersaturation as
a *gradient factor* (the DAN DSSG metric -- a fraction of the M-value).

All pressures are handled in **bar**; depths in **metres of sea water (msw)**
using the diving convention that 10 msw == 1 bar of gauge pressure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ZH-L16C nitrogen half-times (minutes) for the 16 compartments.
# (The N2 half-times are identical across the ZH-L16 A/B/C variants; only the
# a/b coefficients differ, and those are not needed for the DSSG gradient.)
N2_HALFTIMES = (
    4.0, 8.0, 12.5, 18.5, 27.0, 38.3, 54.3, 77.0,
    109.0, 146.0, 187.0, 239.0, 305.0, 390.0, 498.0, 635.0,
)

# ZH-L16 helium half-times (minutes).
HE_HALFTIMES = (
    1.51, 3.02, 4.72, 6.99, 10.21, 14.48, 20.53, 29.11,
    41.20, 55.19, 70.69, 90.34, 115.29, 147.42, 188.24, 240.03,
)

# ZH-L16C nitrogen a/b coefficients (a in bar). Used to derive the M-value
# (maximum tolerated inert-gas tension) and hence the gradient factor.
N2_A = (
    1.2599, 1.0000, 0.8618, 0.7562, 0.6200, 0.5043, 0.4410, 0.4000,
    0.3750, 0.3500, 0.3295, 0.3065, 0.2835, 0.2610, 0.2480, 0.2327,
)
N2_B = (
    0.5050, 0.6514, 0.7222, 0.7825, 0.8126, 0.8434, 0.8693, 0.8910,
    0.9092, 0.9222, 0.9319, 0.9403, 0.9477, 0.9544, 0.9602, 0.9653,
)

# ZH-L16 helium a/b coefficients (identical across the A/B/C variants).
HE_A = (
    1.7424, 1.3830, 1.1919, 1.0458, 0.9220, 0.8205, 0.7305, 0.6502,
    0.5950, 0.5545, 0.5333, 0.5189, 0.5181, 0.5176, 0.5172, 0.5119,
)
HE_B = (
    0.4245, 0.5747, 0.6527, 0.7223, 0.7582, 0.7957, 0.8279, 0.8553,
    0.8757, 0.8903, 0.8997, 0.9073, 0.9122, 0.9171, 0.9217, 0.9267,
)

N_COMPARTMENTS = len(N2_HALFTIMES)

# Alveolar water vapour pressure (Buhlmann constant), bar.
WATER_VAPOUR_PRESSURE = 0.0627

# Nitrogen fraction of dry air.
FN2_AIR = 0.7902

# Standard atmospheric pressure at sea level, bar.
STANDARD_SURFACE_PRESSURE = 1.01325

# Metres of sea water per bar of gauge pressure (diving convention).
MSW_PER_BAR = 10.0


def depth_to_ambient(depth_m: float, surface_pressure: float) -> float:
    """Absolute ambient pressure (bar) at a given depth."""
    return surface_pressure + depth_m / MSW_PER_BAR


@dataclass
class CompartmentState:
    """Tissue tensions for a single compartment (bar)."""

    p_n2: float
    p_he: float

    @property
    def total(self) -> float:
        return self.p_n2 + self.p_he


class TissueModel:
    """Tracks 16 Buhlmann compartments through a dive profile."""

    def __init__(self, surface_pressure: float = STANDARD_SURFACE_PRESSURE):
        self.surface_pressure = surface_pressure
        # Before the dive the tissues are assumed fully saturated breathing
        # air at the surface.
        pp_n2 = (surface_pressure - WATER_VAPOUR_PRESSURE) * FN2_AIR
        self.p_n2 = [pp_n2] * N_COMPARTMENTS
        self.p_he = [0.0] * N_COMPARTMENTS

    @staticmethod
    def _schreiner(p0: float, pi0: float, rate: float, t: float, halftime: float) -> float:
        """Schreiner equation for one compartment over one segment.

        ``p0``   tension at the start of the segment (bar)
        ``pi0``  inspired inert-gas pressure at the start of the segment (bar)
        ``rate`` rate of change of inspired pressure (bar/min)
        ``t``    segment duration (minutes)
        ``halftime`` compartment half-time (minutes)
        """
        k = math.log(2.0) / halftime
        return pi0 + rate * (t - 1.0 / k) - (pi0 - p0 - rate / k) * math.exp(-k * t)

    def step(self, depth_start: float, depth_end: float, seconds: float,
             fn2: float, fhe: float) -> None:
        """Advance the model across one profile segment.

        The breathing-gas inert fractions ``fn2``/``fhe`` are held constant for
        the segment; depth may vary linearly from ``depth_start`` to
        ``depth_end``.
        """
        t = seconds / 60.0
        if t <= 0:
            return

        amb_start = depth_to_ambient(depth_start, self.surface_pressure)
        amb_end = depth_to_ambient(depth_end, self.surface_pressure)

        pi0_n2 = (amb_start - WATER_VAPOUR_PRESSURE) * fn2
        pi0_he = (amb_start - WATER_VAPOUR_PRESSURE) * fhe

        rate_amb = (amb_end - amb_start) / t
        rate_n2 = rate_amb * fn2
        rate_he = rate_amb * fhe

        for i in range(N_COMPARTMENTS):
            self.p_n2[i] = self._schreiner(
                self.p_n2[i], pi0_n2, rate_n2, t, N2_HALFTIMES[i])
            self.p_he[i] = self._schreiner(
                self.p_he[i], pi0_he, rate_he, t, HE_HALFTIMES[i])

    def total_tensions(self) -> list[float]:
        """Total inert-gas tension (N2 + He) per compartment (bar)."""
        return [self.p_n2[i] + self.p_he[i] for i in range(N_COMPARTMENTS)]

    def surface_gradients(self) -> list[float]:
        """Raw supersaturation gradient per compartment at the surface (bar).

        gradient_i = tissue_tension_i - surface_ambient_pressure
        """
        return [t - self.surface_pressure for t in self.total_tensions()]

    def _coefficients(self, i: int) -> tuple[float, float]:
        """Gas-weighted Buhlmann a/b coefficients for compartment ``i``."""
        pn2, phe = self.p_n2[i], self.p_he[i]
        total = pn2 + phe
        if total <= 0:
            return N2_A[i], N2_B[i]
        a = (N2_A[i] * pn2 + HE_A[i] * phe) / total
        b = (N2_B[i] * pn2 + HE_B[i] * phe) / total
        return a, b

    def gradient_factors(self, ambient: float | None = None) -> list[float]:
        """Gradient factor per compartment at a given ambient pressure.

        The gradient factor is the inert-gas supersaturation expressed as a
        fraction of the maximum tolerated supersaturation (M-value), per
        Baker (1998)::

            M(P_amb) = a + P_amb / b
            GF       = (P_tissue - P_amb) / (M(P_amb) - P_amb)

        GF = 1.0 means the compartment sits exactly at its ZH-L16C M-value;
        GF > 1.0 means it has surfaced beyond the tolerated limit. ``ambient``
        defaults to the surface pressure (i.e. the *surface* gradient factor).
        """
        p_amb = self.surface_pressure if ambient is None else ambient
        gfs: list[float] = []
        for i in range(N_COMPARTMENTS):
            tissue = self.p_n2[i] + self.p_he[i]
            a, b = self._coefficients(i)
            m_value = a + p_amb / b
            denom = m_value - p_amb
            gfs.append((tissue - p_amb) / denom if denom > 0 else 0.0)
        return gfs
