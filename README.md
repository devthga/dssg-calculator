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
holds *above* the surrounding pressure at the moment of surfacing.

How it is computed here:

1. A **Bühlmann ZH‑L16** model is initialised assuming the diver was saturated
   breathing air at the surface before the dive.
2. The model is integrated segment‑by‑segment through the recorded depth/time
   profile using the **Schreiner equation**, with the breathing gas in effect
   at each waypoint (air, nitrox, or trimix — nitrogen *and* helium are
   tracked across all 16 compartments).
3. At surfacing, each compartment's gradient is
   `tissue inert‑gas tension − surface pressure`.
4. The dive's **DSSG** is the largest gradient across all compartments — the
   *controlling* (leading) compartment, i.e. the peak supersaturation taken to
   the surface.

Gradients are reported in **bar** and in **metres of sea water (msw)**
(`1 bar ≈ 10 msw`). A higher DSSG means more dissolved gas relative to ambient
pressure and a greater theoretical bubble‑formation risk.

> Only the compartment half‑times are needed to integrate gas tensions, so the
> result is independent of the ZH‑L16 a/b sub‑variant (those coefficients only
> affect ceiling / M‑value calculations, which the DSSG does not use).

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
  buhlmann.py          ZH-L16 tissue model (Schreiner integration)
  parser.py            MacDive UDDF parser
  calculator.py        DSSG computation per dive
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
