# vino — dive-log DSSG analyzer

Takes a dive-log export, calculates the **DAN Surface Supersaturation Gradient
(DSSG)** for every dive, produces a statistical overview, and builds a
browsable HTML report. Use it as a **command-line tool** or as a **FastAPI web
application** where you upload a file and the analysis runs on the server.

Supports exports from **any app that includes a per-dive depth/time profile and
gas mix** — see [Supported formats](#supported-formats) (MacDive, Subsurface,
and other UDDF exporters).

> Licensed for **non-commercial use only** — AGPL-3.0 + Commons Clause. See
> [License](#license).

The DSSG calculator core and CLI use **only the Python standard library**. The
web application additionally needs FastAPI (see `requirements.txt`).

## Quick start (CLI)

```bash
# Export your dives (e.g. MacDive: File ▸ Export ▸ UDDF), then:
python3 dssg_calculator.py path/to/your_export.uddf -o report
open report/index.html        # macOS   (xdg-open on Linux)
```

Don't have an export handy? Generate realistic samples and try it:

```bash
python3 sample/make_sample.py                 # MacDive-style UDDF
python3 sample/make_subsurface_sample.py      # Subsurface .ssrf
python3 dssg_calculator.py sample/macdive_sample.uddf -o report
```

## Web application (FastAPI)

Upload a dive log in the browser; the file is **stored permanently on the
server** and analysed **server-side**, then you can browse the report.

```bash
pip install -r requirements.txt
python3 serve.py                       # http://127.0.0.1:8000
# or:  uvicorn dssg.web:app --reload
```

- **Upload** a UDDF or Subsurface export on the landing page.
- The raw file is kept under `data/uploads/<id>/` and the generated report under
  `data/reports/<id>/` (configurable with `--data` / `DSSG_DATA_DIR`).
- Past analyses are listed on the landing page and via a JSON API:
  `GET /api/analyses` and `GET /api/analyses/{id}`.

**Hardening for untrusted uploads:** XML is parsed with DTD/entity declarations
disabled (blocks "billion-laughs" and XXE), uploads are size-capped, generated
CSV is protected against spreadsheet formula injection, and report/download
paths are validated against directory traversal.

## Supported formats

Any app that can export a per-dive **depth/time profile** plus the **breathing
gas** can be analysed. The format is auto-detected:

| Format | Apps |
|--------|------|
| **UDDF** (`.uddf` / `.xml`) | MacDive, Subsurface, Shearwater, Suunto DM, DivingLog, Garmin Dive, and other UDDF exporters |
| **Subsurface** native XML (`.ssrf` / `.xml`) | Subsurface |

Summary-only exports (most plain CSVs, without per-sample depth/time) cannot be
analysed and are rejected with a clear message.

## Deployment

The repo ships a Docker Compose stack (app + Caddy with automatic HTTPS) for a
cheap single-box deployment with persistent storage:

```bash
DOMAIN=dssg.example.com docker compose up -d --build   # or just: docker compose up
```

Because uploads are stored permanently, the app needs a persistent disk — a
~$4–5/month VPS is the cheapest fit. See [`DEPLOY.md`](DEPLOY.md) for VPS,
Fly.io (with a volume), and hardening notes.

## What you get

In the output directory (`report/` by default):

| File | Contents |
|------|----------|
| `index.html` | Overview website: summary cards, DSSG histogram, correlations, and a sortable table of all dives (click a dive to drill in). |
| `dive_<n>.html` | Per-dive page: depth profile, per-compartment gradient-factor chart, gas mixes and dive details. |
| `dives.csv` | One row per dive (date, depth, duration, DSSG, leading compartment, risk band, DCS rate). |
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

The implementation follows the methodology of the two DAN papers:

1. A **Bühlmann ZH‑L16C** model is initialised assuming the diver was saturated
   breathing air at the surface before the dive.
2. The recorded profile is **normalised to a consistent surfacing moment**:
   trailing samples ≤ 0.5 m (with no later descent ≥ 1 m) are collapsed into a
   single 0 m data point, since most dive computers stop logging at 0.5–1 m
   rather than exactly 0 m.
3. The model is integrated segment‑by‑segment through the profile using the
   **Schreiner equation**, with the breathing gas in effect at each waypoint
   (air, nitrox, or trimix — nitrogen *and* helium across all 16 compartments).
4. At surfacing, each compartment's supersaturation is expressed as a
   **gradient factor (GF)** — the inert‑gas overpressure as a *fraction of the
   M‑value* (Baker, 1998):

   ```
   M(P_amb) = a + P_amb / b          (ZH‑L16C a/b coefficients)
   GF       = (P_tissue − P_amb) / (M(P_amb) − P_amb)
   ```

5. The dive's **DSSG** is the GF of the **leading compartment** — the one with
   the *highest gradient factor / critical ratio* at surfacing (also reported as
   `DSSG_COMPRT`, the compartment number). Because the M‑value differs per
   compartment, this is **not** generally the highest‑*tension* compartment.

The DSSG is therefore a **dimensionless gradient factor**, where **GF = 1.0
means surfacing exactly at the ZH‑L16C M‑value limit**. In the DAN DSL 2024
study the mean was **0.71 ± 0.14** (range **0.25–1.40**); this tool reproduces
that scale (the bundled demo averages ≈ 0.69). The raw gradient in bar is also
reported as a secondary figure.

### Empirical DCS risk (DAN DSL 2024, Table 3)

The report colour‑codes each dive and shows the observed DCS incidence for its
DSSG band:

| DSSG (GF) | Risk band | Observed DCS rate |
|---|---|---|
| ≤ 0.5 | Very low | ~0% |
| 0.6 | Low | 0.012% |
| 0.7 | Moderate | 0.095% |
| 0.8 | Elevated | 0.720% |
| 0.9 | High | 3.344% |
| ≥ 1.0 | Very high | 37.532% |

**Sources:**
- Marroni A. et al., *Identification of DCS risk factors in recreational
  diving: multifactorial model based on the DAN DSL Database 2024*,
  International Maritime Health, 2026.
- Cialoni D., Pieri M., Balestra C., Marroni A., *Dive Risk Factors, Gas Bubble
  Formation, and Decompression Illness in Recreational SCUBA Diving: Analysis
  of DAN Europe DSL Data Base*, Frontiers in Psychology, 2017; 8: 1587
  ([doi:10.3389/fpsyg.2017.01587](https://doi.org/10.3389/fpsyg.2017.01587)) —
  the paper defining the gradient‑factor calculation referenced above.

**This is an educational/analysis tool, not a dive planner or a medical
device. Do not use it to plan dives or make decompression decisions.**

## Input requirements

A dive is analysable only if its export contains the full **depth/time sample
profile** plus the **breathing gas**. The XML parsers are namespace‑tolerant
and fall back to sensible defaults (air, sea‑level atmospheric pressure) when
optional fields are absent. Dives without profile samples are skipped (the DSSG
cannot be computed without a profile).

## Project layout

```
dssg/
  buhlmann.py          ZH-L16C tissue model (Schreiner integration)
  parser.py            UDDF + Subsurface parsers, format detection, safe XML
  calculator.py        DSSG computation + surfacing correction
  risk.py              DAN DSL 2024 empirical risk bands / DCS rates
  statistics_report.py per-dive summaries + aggregate statistics
  report.py            self-contained HTML + inline-SVG report, CSV/JSON output
  store.py             permanent upload storage + analysis (framework-agnostic)
  web.py               FastAPI web application
  cli.py               command-line interface
dssg_calculator.py     CLI launcher
serve.py               web app launcher (uvicorn)
requirements.txt       web-app dependencies (FastAPI/uvicorn)
sample/                demo export generators (UDDF + Subsurface)
tests/                 unit + web tests (stdlib unittest + FastAPI TestClient)
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## License

This project is licensed under the **GNU AGPL-3.0 with the Commons Clause**
(see [`LICENSE`](LICENSE)). In short: you may use, modify, study and share it —
including running it as a network service — provided you make complete
corresponding source available to your users (AGPL). The **Commons Clause
prohibits selling** the software or a service whose value derives substantially
from it. For commercial/selling rights, contact the copyright holder. This is a
source‑available, **non‑commercial** license and is not OSI "open source".
