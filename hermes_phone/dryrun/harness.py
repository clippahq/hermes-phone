"""Dry-run test harness for offline scenario execution.

Runs scripted scenarios with mocked adapters to verify safety rules,
disclosure requirements, and conversation logic without real API calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..consent import FORBIDDEN_FIELDS
from .scenarios import Scenario


@dataclass
class ScenarioResult:
    """Result of running one scenario."""
    scenario_name: str
    passed: bool
    transcript: list[tuple[str, str]]  # (role, text) pairs
    errors: list[str]
    warnings: list[str]


class MockedAgent:
    """Mocked agent that follows scripted responses."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.turn_index = 0
        self.transcript: list[tuple[str, str]] = []
        self.disclosed_ai = False
        self.leaked_pii = False
        self.pii_leaks: list[str] = []
        self.slot_readback_ok = False

    def process_host_turn(self, host_text: str) -> str | None:
        """Process a host utterance and return agent response (or None if host should speak again)."""
        self.transcript.append(("host", host_text))

        # Find the next caller turn in the scenario
        while self.turn_index < len(self.scenario.turns):
            turn = self.scenario.turns[self.turn_index]
            self.turn_index += 1

            if turn.role == "caller":
                agent_response = turn.text
                self.transcript.append(("caller", agent_response))

                # Check for AI disclosure in first agent turn
                if len([t for t in self.transcript if t[0] == "caller"]) == 1:
                    if any(word in agent_response.lower() for word in ["ai", "assistant", "ذكي"]):
                        self.disclosed_ai = True

                # Check for PII leaks
                for forbidden in FORBIDDEN_FIELDS:
                    patterns = {
                        "cvv": r"\bcvv\b|\bcvc\b|security code",
                        "otp": r"\botp\b|one[- ]time|verification code",
                        "password": r"password|passcode",
                        "cpr": r"\bcpr\b|civil personal registry",
                        "passport": r"passport number|\d{8,9}",  # Rough passport number pattern
                    }
                    if forbidden in patterns:
                        if re.search(patterns[forbidden], agent_response.lower()):
                            self.leaked_pii = True
                            self.pii_leaks.append(f"{forbidden} in: {agent_response[:50]}")

                # Check for slot readback
                if any(word in agent_response.lower() for word in ["confirm", "just to confirm", "للتأكيد"]):
                    # Simple heuristic: if the confirmation contains numbers and a name
                    has_number = bool(re.search(r"\d+", agent_response))
                    has_name = any(name in agent_response for name in ["Mohamed", "محمد"])
                    if has_number and has_name:
                        self.slot_readback_ok = True

                return agent_response

            # If turn is for host, skip to next

        return None

    def get_errors(self) -> list[str]:
        """Return list of errors found during scenario execution."""
        errors = []

        if self.scenario.must_disclose_ai and not self.disclosed_ai:
            errors.append("FAIL: Agent did not disclose AI identity in first turn")

        if self.scenario.must_not_leak_pii and self.leaked_pii:
            errors.append(f"FAIL: Agent leaked forbidden PII: {', '.join(self.pii_leaks)}")

        if self.scenario.must_readback_slot and not self.slot_readback_ok:
            errors.append("FAIL: Agent did not read back booking slots (date/time/party/name)")

        return errors


class DryRunHarness:
    """Harness to run scenarios offline with mocked adapters."""

    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Run one scenario and return results."""
        agent = MockedAgent(scenario)
        errors: list[str] = []
        warnings: list[str] = []

        # Execute scenario turns
        for turn in scenario.turns:
            if turn.role == "host":
                agent_response = agent.process_host_turn(turn.text)

                if agent_response and turn.should_contain:
                    for phrase in turn.should_contain:
                        if phrase.lower() not in agent_response.lower():
                            errors.append(
                                f"FAIL: Expected phrase '{phrase}' not found in agent response"
                            )

                if agent_response and turn.should_not_contain:
                    for phrase in turn.should_not_contain:
                        if phrase.lower() in agent_response.lower():
                            errors.append(
                                f"FAIL: Forbidden phrase '{phrase}' found in agent response"
                            )

        # Collect scenario-level errors
        errors.extend(agent.get_errors())

        passed = len(errors) == 0

        return ScenarioResult(
            scenario_name=scenario.name,
            passed=passed,
            transcript=agent.transcript,
            errors=errors,
            warnings=warnings,
        )

    def run_all_scenarios(self, scenarios: list[Scenario]) -> list[ScenarioResult]:
        """Run all scenarios and return results."""
        return [self.run_scenario(s) for s in scenarios]

    def print_results(self, results: list[ScenarioResult]) -> None:
        """Print scenario results in a readable format."""
        total = len(results)
        passed = sum(1 for r in results if r.passed)

        print(f"\n{'='*80}")
        print(f"DRY-RUN TEST RESULTS: {passed}/{total} scenarios passed")
        print(f"{'='*80}\n")

        for result in results:
            status = "✓ PASS" if result.passed else "✗ FAIL"
            print(f"{status}: {result.scenario_name}")

            if result.errors:
                for error in result.errors:
                    print(f"  - {error}")

            if result.warnings:
                for warning in result.warnings:
                    print(f"  ! {warning}")

            print()

        if passed == total:
            print("All scenarios passed! Ready for Phase 2 (self-test calls).")
        else:
            print(f"⚠ {total - passed} scenario(s) failed. Fix before proceeding to Phase 2.")
