"""Buhlmann ZH-L16 inert-gas tissue model.

The model is used to track the partial pressure of the inert gases (nitrogen
and helium) in 16 theoretical tissue compartments while a diver moves through
a depth/time profile.  At the moment the diver reaches the surface the
*supersaturation gradient* of each compartment is the amount by which its
dissolved inert-gas tension exceeds the ambient (surface) pressure.

Only the compartment half-times are needed to integrate the gas tensions, so
the model is independent of the ZH-L16 a/b sub-variant (those coefficients
only matter for ceiling / M-value calculations, which the DSSG does not use).

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
        """Supersaturation gradient per compartment relative to the surface.

        gradient_i = tissue_tension_i - surface_ambient_pressure
        """
        return [t - self.surface_pressure for t in self.total_tensions()]
