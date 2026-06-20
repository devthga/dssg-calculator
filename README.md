# vino — MacDive DSSG calculator

Takes an export from the [MacDive](https://www.mac-dive.com/) dive-logging app,
calculates the **DAN Surface Supersaturation Gradient (DSSG)** for every dive,
produces a statistical overview, and builds a small browsable HTML website for
exploring the dives and their DSSG.

Pure Python 3 standard library — **no third-party dependencies, fully offline**
(charts are inline SVG generated in Python; the website needs no internet).

## Quick start

```bash
# 1. Export your dives from MacDive:  File ▸ Export ▸ UDDF   (.uddf / .xml)
# 2. Run the calculator:
python3 dssg_calculator.py path/to/your_macdive_export.uddf -o report

# 3. Open the website:
open report/index.html        # macOS   (xdg-open on Linux)
```

Don't have an export handy? Generate a realistic sample and try it:

```bash
python3 sample/make_sample.py
python3 dssg_calculator.py sample/macdive_sample.uddf -o report
```

## What you get

In the output directory (`report/` by default):

| File | Contents |
|------|----------|
| `index.html` | Overview website: summary cards, DSSG histogram, correlations, and a sortable table of all dives (click a dive to drill in). |
| `dive_<n>.html` | Per-dive page: depth profile, per-compartment surface-gradient chart, gas mixes and dive details. |
| `dives.csv` | One row per dive (date, depth, duration, DSSG in bar & msw, leading compartment). |
| `statistics.json` | Machine-readable statistical overview. |

### CLI options

```
python3 dssg_calculator.py INPUT [-o OUTPUT_DIR] [--no-html]
```

- `-o, --output`  Output directory (default `report`).
- `--no-html`     Write only `dives.csv` + `statistics.json`, skip the website.

You can also run it as a module: `python3 -m dssg.cli INPUT`.

## What is the DSSG?

The **DAN Surface Supersaturation Gradient** estimates the decompression
stress a diver carries to the surface — how much dissolved inert gas a tissue
holds *above* the surrounding pressure at the moment of surfacing. In the DAN
DSL Database 2024 study (127,957 dives) it was the **single strongest
independent predictor of decompression sickness**.

The implementation follows the paper's methodology:

1. A **Bühlmann ZH‑L16C** model is initialised assuming the diver was saturated
   breathing air at the surface before the dive.
2. The recorded profile is **normalised to a consistent surfacing moment**:
   trailing samples ≤ 0.5 m (with no later descent ≥ 1 m) are collapsed into a
   single 0 m data point, since most dive computers stop logging at 0.5–1 m
   rather than exactly 0 m.
3. The model is integrated segment‑by‑segment through the profile using the
   **Schreiner equation**, with the breathing gas in effect at each waypoint
   (air, nitrox, or trimix — nitrogen *and* helium across all 16 compartments).
4. At surfacing, each compartment's gradient is
   `tissue inert‑gas tension − surface pressure`.
5. The dive's **DSSG** is the gradient of the **leading compartment** — the one
   with the *highest critical ratio* at surfacing (also reported as
   `DSSG_COMPRT`, the compartment number). Because ambient pressure is identical
   for every compartment at the surface, the highest‑ratio compartment is also
   the highest‑gradient one.

The DSSG is reported in **bar/ata** (the paper's unit; mean **0.71 ± 0.14**,
range **0.25–1.40**), with msw shown as a secondary diver‑friendly figure.

### Empirical DCS risk (DAN DSL 2024, Table 3)

The report colour‑codes each dive and shows the observed DCS incidence for its
DSSG band:

| DSSG (bar/ata) | Risk band | Observed DCS rate |
|---|---|---|
| ≤ 0.5 | Very low | ~0% |
| 0.6 | Low | 0.012% |
| 0.7 | Moderate | 0.095% |
| 0.8 | Elevated | 0.720% |
| 0.9 | High | 3.344% |
| ≥ 1.0 | Very high | 37.532% |

> Only the compartment half‑times are needed to integrate gas tensions, so the
> result is independent of the ZH‑L16 a/b sub‑variant (those coefficients only
> affect ceiling / M‑value calculations, which the DSSG does not use).

**Source:** Marroni A. et al., *Identification of DCS risk factors in
recreational diving: multifactorial model based on the DAN DSL Database 2024*,
International Maritime Health, 2026.

**This is an educational/analysis tool, not a dive planner or a medical
device. Do not use it to plan dives or make decompression decisions.**

## Input format

MacDive's **UDDF** export is used because it contains the full depth/time
sample profile and gas mixes that the calculation needs. The parser is
namespace‑tolerant and falls back to sensible defaults (air, sea‑level
atmospheric pressure) when optional fields are absent. Dives without profile
samples are skipped (the DSSG cannot be computed without a profile).

## Project layout

```
dssg/
  buhlmann.py          ZH-L16C tissue model (Schreiner integration)
  parser.py            MacDive UDDF parser
  calculator.py        DSSG computation + surfacing correction
  risk.py              DAN DSL 2024 empirical risk bands / DCS rates
  statistics_report.py per-dive summaries + aggregate statistics
  report.py            self-contained HTML + inline-SVG report
  cli.py               command-line interface
dssg_calculator.py     convenience launcher
sample/make_sample.py  generates a demo UDDF export
tests/test_dssg.py     unit tests (stdlib unittest)
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```
