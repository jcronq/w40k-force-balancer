#!/usr/bin/env python3
"""Backwards-compatible shim for the old `w40k_sim_v2.py` monolith.

The simulator was refactored out of this 1572-LOC file into the
`w40k_force_balancer` package (see w40k_force_balancer/__init__.py for
scope + STAT-APPROX ledger). This shim re-exports the package's CLI so
existing invocations `python3 w40k_sim_v2.py ...` keep working.

For the new idiom, run `python3 -m w40k_force_balancer ...` instead.
"""
from __future__ import annotations

import sys

from w40k_force_balancer.cli import main


if __name__ == "__main__":
    sys.exit(main())
