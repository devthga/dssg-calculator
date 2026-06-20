"""Empirical DCS risk associated with DSSG values.

The risk bands and decompression-sickness (DCS) incidence rates below are taken
directly from the DAN DSL Database 2024 study:

    Marroni A. et al., "Identification of DCS risk factors in recreational
    diving: multifactorial model based on the DAN DSL Database 2024",
    International Maritime Health, 2026 -- Table 3 (univariate analysis of the
    DCS rate as a function of the DAN Surface Supersaturation Gradient).

In that study the mean DSSG was 0.71 +/- 0.14 (range 0.25-1.40); median DSSG
was 0.743 for non-DCS dives versus 0.866 for DCS dives (p < 0.001).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskBand:
    label: str          # human-readable risk level
    colour: str         # CSS colour used in the report
    dcs_rate_pct: float # observed DCS incidence for this band (DAN DSL 2024)


# Ordered from highest threshold to lowest; the first band whose lower bound is
# met applies. Lower bound is the DSSG value (gradient factor) at which the
# band starts.
_BANDS: tuple[tuple[float, RiskBand], ...] = (
    (1.0, RiskBand("Very high", "#ef4444", 37.532)),
    (0.9, RiskBand("High", "#f87171", 3.344)),
    (0.8, RiskBand("Elevated", "#fb923c", 0.720)),
    (0.7, RiskBand("Moderate", "#fbbf24", 0.095)),
    (0.6, RiskBand("Low", "#a3e635", 0.012)),
    (0.0, RiskBand("Very low", "#34d399", 0.0)),
)

# The full Table 3 lookup (DSSG given as a gradient factor), for display as a
# reference on the report.
DAN_DSL_2024_TABLE = (
    ("≤ 0.5", 0.0),
    ("0.6", 0.012),
    ("0.7", 0.095),
    ("0.8", 0.720),
    ("0.9", 3.344),
    ("≥ 1.0", 37.532),
)

# Reference statistics from the paper for context in the report.
PAPER_MEAN_DSSG = 0.71
PAPER_SD_DSSG = 0.14
PAPER_MEDIAN_NON_DCS = 0.743
PAPER_MEDIAN_DCS = 0.866


def classify(dssg: float) -> RiskBand:
    """Return the empirical risk band for a DSSG (gradient factor) value."""
    for lower, band in _BANDS:
        if dssg >= lower:
            return band
    return _BANDS[-1][1]
