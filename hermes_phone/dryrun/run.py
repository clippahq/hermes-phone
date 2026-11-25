#!/usr/bin/env python3
"""CLI to run dry-run scenarios offline.

Usage:
    python -m hermes_phone.dryrun.run
    python -m hermes_phone.dryrun.run --scenario happy_path
"""
from __future__ import annotations

import argparse
import sys

from .harness import DryRunHarness
from .scenarios import SCENARIOS


def main() -> int:
    parser = argparse.ArgumentParser(description="Run dry-run test scenarios offline")
    parser.add_argument(
        "--scenario",
        type=str,
        help="Run a specific scenario by name (default: run all)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full transcripts",
    )
    args = parser.parse_args()
    
    harness = DryRunHarness()
    
    if args.scenario:
        scenarios = [s for s in SCENARIOS if s.name == args.scenario]
        if not scenarios:
            print(f"Error: Scenario '{args.scenario}' not found")
            print(f"Available scenarios: {', '.join(s.name for s in SCENARIOS)}")
            return 1
    else:
        scenarios = SCENARIOS
    
    results = harness.run_all_scenarios(scenarios)
    
    if args.verbose:
        for result in results:
            print(f"\n{'='*80}")
            print(f"Scenario: {result.scenario_name}")
            print(f"{'='*80}")
            for role, text in result.transcript:
                speaker = "AGENT" if role == "caller" else "HOST"
                print(f"{speaker}: {text}")
            print()
    
    harness.print_results(results)
    
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
