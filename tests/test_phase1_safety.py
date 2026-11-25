"""Tests for Phase 1 safety enhancements: Bahrain blocks, CPR/passport, spend caps."""
from __future__ import annotations

from datetime import UTC

from hermes_phone import consent, safety, spend
from hermes_phone.store import Store


class TestBahrainSafetyBlocks:
    """Test Bahrain-specific emergency and premium number blocks."""

    def test_bahrain_emergency_994_blocked(self):
        """994 (Bahrain Ambulance) must be blocked."""
        result = safety.is_blocked("994")
        assert not result.ok
        assert "emergency" in result.reason.lower()

    def test_bahrain_emergency_998_blocked(self):
        """998 (Bahrain Police non-emergency) must be blocked."""
        result = safety.is_blocked("998")
        assert not result.ok
        assert "emergency" in result.reason.lower()

    def test_bahrain_premium_9xxx_blocked(self):
        """Bahrain +973 9xxx xxxx premium numbers must be blocked."""
        result = safety.is_blocked("+97390001234")
        assert not result.ok
        assert "premium" in result.reason.lower()

    def test_bahrain_premium_9xxx_various_formats(self):
        """Test various formats of Bahrain premium numbers."""
        test_numbers = [
            "+97391234567",
            "0097392345678",
        ]
        for number in test_numbers:
            result = safety.is_blocked(number)
            assert not result.ok, f"Should block {number}"
            assert "premium" in result.reason.lower()

    def test_bahrain_normal_number_allowed(self):
        """Normal Bahrain mobile numbers should not be blocked by premium check."""
        # +973 3xxx xxxx is a normal mobile range, not premium
        result = safety.is_blocked("+97336001234")
        # Should pass the premium check (may still need allowlist)
        assert result.ok or "premium" not in result.reason.lower()


class TestCPRPassportForbidden:
    """Test that CPR and passport are in FORBIDDEN_FIELDS."""

    def test_cpr_in_forbidden_fields(self):
        """CPR must be in FORBIDDEN_FIELDS."""
        assert "cpr" in consent.FORBIDDEN_FIELDS

    def test_passport_in_forbidden_fields(self):
        """Passport must be in FORBIDDEN_FIELDS."""
        assert "passport" in consent.FORBIDDEN_FIELDS

    def test_cpr_key_classified(self):
        """Keys like 'cpr_number' should be classified as cpr."""
        assert consent.classify_key("cpr_number") == "cpr"
        assert consent.classify_key("bahrain_id") == "cpr"
        assert consent.classify_key("civil_personal_registry") == "cpr"

    def test_passport_key_classified(self):
        """Keys like 'passport_number' should be classified as passport."""
        assert consent.classify_key("passport_number") == "passport"
        assert consent.classify_key("travel_document") == "passport"

    def test_cpr_question_classified(self):
        """Questions asking for CPR should be classified as forbidden."""
        field = consent.classify_question("", "What is your CPR number?")
        assert field == "cpr"

        field = consent.classify_question("", "I need your Bahrain ID")
        assert field == "cpr"

    def test_passport_question_classified(self):
        """Questions asking for passport should be classified as forbidden."""
        field = consent.classify_question("", "What is your passport number?")
        assert field == "passport"


class TestDailySpendCaps:
    """Test daily spend cap enforcement in Bahrain timezone."""

    def test_estimate_call_cost(self):
        """Call cost estimation should match expected rates."""
        # 1 minute call with default rates
        cost = spend.estimate_call_cost(60)
        # Twilio $0.2267 + Deepgram $0.0145 + ElevenLabs $0.0360 + Grok $0.0120 = $0.2892/min
        assert 0.28 <= cost <= 0.30, f"Expected ~$0.29, got ${cost:.2f}"

        # 2.5 minute call
        cost = spend.estimate_call_cost(150)
        assert 0.70 <= cost <= 0.75, f"Expected ~$0.72, got ${cost:.2f}"

    def test_check_daily_limits_no_calls(self):
        """With no calls today, should pass limits."""
        store = Store()
        try:
            result = spend.check_daily_limits(store, estimated_cost_usd=0.5, estimated_minutes=2.0)
            assert result.ok
            assert result.current_spend == 0.0
            assert result.current_calls == 0
        finally:
            store.close()

    def test_default_limits_from_env(self):
        """Default limits should be $6/day, 20min/day, 10 calls/day."""
        max_spend, max_minutes, max_calls = spend._get_limits({})
        assert max_spend == 6.0
        assert max_minutes == 20.0
        assert max_calls == 10

    def test_custom_limits_from_env(self):
        """Custom limits should be read from environment."""
        env = {
            "HERMES_PHONE_MAX_DAILY_SPEND_USD": "10.0",
            "HERMES_PHONE_MAX_DAILY_MINUTES": "30.0",
            "HERMES_PHONE_MAX_DAILY_CALLS": "15",
        }
        max_spend, max_minutes, max_calls = spend._get_limits(env)
        assert max_spend == 10.0
        assert max_minutes == 30.0
        assert max_calls == 15

    def test_bahrain_date_format(self):
        """Bahrain date should be in YYYY-MM-DD format."""
        from datetime import datetime

        now = datetime(2026, 11, 25, 20, 30, tzinfo=UTC)
        bahrain_date = spend._get_bahrain_date(now)
        # Bahrain is UTC+3, so 20:30 UTC is 23:30 Bahrain (same day)
        assert bahrain_date == "2026-11-25"

        # Edge case: 23:00 UTC is 02:00 next day in Bahrain
        now = datetime(2026, 11, 25, 23, 0, tzinfo=UTC)
        bahrain_date = spend._get_bahrain_date(now)
        assert bahrain_date == "2026-11-26"


class TestStoreSchemaV7:
    """Test that store schema v7 includes bahrain_date and cost_usd."""

    def test_schema_version_is_7(self):
        """Store schema version should be 7."""
        from hermes_phone.store import SCHEMA_VERSION
        assert SCHEMA_VERSION == 7

    def test_store_has_bahrain_date_method(self):
        """Store should have get_calls_by_bahrain_date method."""
        store = Store()
        try:
            # Method should exist
            assert hasattr(store, "get_calls_by_bahrain_date")
            # Should return empty list for non-existent date
            calls = store.get_calls_by_bahrain_date("2026-11-25")
            assert isinstance(calls, list)
        finally:
            store.close()
