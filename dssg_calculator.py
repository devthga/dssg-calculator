#!/usr/bin/env python3
"""Convenience launcher for the MacDive DSSG calculator.

Equivalent to ``python -m dssg.cli``.  Example::

    python dssg_calculator.py my_macdive_export.uddf -o report
"""

from dssg.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
