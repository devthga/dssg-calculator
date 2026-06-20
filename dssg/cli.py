"""Command-line interface for the dive-log DSSG calculator."""

from __future__ import annotations

import argparse
import os
import sys

from .calculator import compute_dssg
from .parser import parse_dive_log
from .report import write_data, write_report
from .statistics_report import build_statistics, summarise_dive


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="dssg",
        description="Calculate the DAN Surface Supersaturation Gradient (DSSG) "
                    "for every dive in a MacDive UDDF export and build a "
                    "browsable HTML report.",
    )
    parser.add_argument("input", help="Path to the MacDive UDDF export (.uddf/.xml)")
    parser.add_argument("-o", "--output", default="report",
                        help="Output directory for the report (default: report)")
    parser.add_argument("--no-html", action="store_true",
                        help="Skip HTML generation; write CSV + JSON only")
    args = parser.parse_args(argv)

    if not os.path.exists(args.input):
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    try:
        fmt, dives = parse_dive_log(args.input)
    except Exception as exc:  # noqa: BLE001 - surface a friendly message
        print(f"error: could not parse dive log: {exc}", file=sys.stderr)
        return 1

    if not dives:
        print("error: no dives with profile samples found in the export.",
              file=sys.stderr)
        return 1
    print(f"Detected format: {fmt}")

    results = [compute_dssg(d) for d in dives]
    summaries = [summarise_dive(d, r) for d, r in zip(dives, results)]
    stats = build_statistics(summaries)

    if args.no_html:
        write_data(args.output, summaries, stats)
    else:
        write_report(args.output, dives, results, summaries, stats)

    # Console summary.
    d = stats["dssg"]
    print(f"Analysed {stats['dive_count']} dive(s).")
    print(f"  DSSG (gradient factor)  mean {d.get('mean', 0):.3f} | "
          f"median {d.get('median', 0):.3f} | "
          f"min {d.get('min', 0):.3f} | max {d.get('max', 0):.3f}")
    most = stats.get("most_stressful_dive")
    if most:
        print(f"  Highest DSSG: dive #{most['number']} "
              f"(GF {most['dssg']:.3f}, {most['risk_band']} risk, "
              f"{most.get('location') or 'unknown site'})")
    print(f"Report written to: {os.path.abspath(args.output)}")
    if not args.no_html:
        print(f"  Open: {os.path.join(os.path.abspath(args.output), 'index.html')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
