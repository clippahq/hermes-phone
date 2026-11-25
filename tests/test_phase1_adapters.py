"""Tests for Phase 1 adapter implementations."""
from __future__ import annotations

from hermes_phone.adapters import (
    AudioChunk,
    LLMMessage,
    TranscriptSegment,
    TTSChunk,
)


class TestAdapterProtocols:
    """Test that adapter protocols are properly defined."""

    def test_audio_chunk_dataclass(self):
        """AudioChunk should have required fields."""
        chunk = AudioChunk(data=b"test", format="audio/pcmu", timestamp_ms=1000)
        assert chunk.data == b"test"
        assert chunk.format == "audio/pcmu"
        assert chunk.timestamp_ms == 1000

    def test_transcript_segment_dataclass(self):
        """TranscriptSegment should have required fields."""
        segment = TranscriptSegment(
            text="Hello world",
            is_final=True,
            language="en",
            confidence=0.95,
        )
        assert segment.text == "Hello world"
        assert segment.is_final is True
        assert segment.language == "en"
        assert segment.confidence == 0.95

    def test_llm_message_dataclass(self):
        """LLMMessage should have required fields."""
        msg = LLMMessage(
            role="user",
            content="Test message",
            tool_calls=None,
            tool_call_id=None,
        )
        assert msg.role == "user"
        assert msg.content == "Test message"
        assert msg.tool_calls is None

    def test_tts_chunk_dataclass(self):
        """TTSChunk should have required fields."""
        chunk = TTSChunk(
            audio=b"audio_data",
            format="ulaw_8000",
            sequence=5,
        )
        assert chunk.audio == b"audio_data"
        assert chunk.format == "ulaw_8000"
        assert chunk.sequence == 5


class TestAdapterImports:
    """Test that adapter implementations can be imported."""

    def test_deepgram_adapter_imports(self):
        """DeepgramSTTAdapter should be importable."""
        from hermes_phone.adapters.deepgram import DeepgramSTTAdapter

        assert DeepgramSTTAdapter is not None

    def test_xai_adapter_imports(self):
        """XAILLMAdapter should be importable."""
        from hermes_phone.adapters.xai import XAILLMAdapter

        assert XAILLMAdapter is not None

    def test_elevenlabs_adapter_imports(self):
        """ElevenLabsTTSAdapter should be importable."""
        from hermes_phone.adapters.elevenlabs import ElevenLabsTTSAdapter

        assert ElevenLabsTTSAdapter is not None

    def test_twilio_adapter_imports(self):
        """TwilioTelephonyAdapter should be importable."""
        from hermes_phone.adapters.twilio import TwilioTelephonyAdapter

        assert TwilioTelephonyAdapter is not None


class TestDeepgramAdapter:
    """Test Deepgram adapter initialization."""

    def test_deepgram_adapter_init(self):
        """DeepgramSTTAdapter should initialize with required params."""
        from hermes_phone.adapters.deepgram import DeepgramSTTAdapter

        adapter = DeepgramSTTAdapter(
            api_key="test_key",
            language="multi",
            model="nova-3",
            endpointing_ms=300,
        )

        assert adapter.api_key == "test_key"
        assert adapter.language == "multi"
        assert adapter.model == "nova-3"
        assert adapter.endpointing_ms == 300

    def test_deepgram_bahraini_keyterms(self):
        """DeepgramSTTAdapter should have Bahraini keyterms."""
        from hermes_phone.adapters.deepgram import BAHRAINI_KEYTERMS

        assert "Al Khalifa" in BAHRAINI_KEYTERMS
        assert "Manama" in BAHRAINI_KEYTERMS
        assert "Adliya" in BAHRAINI_KEYTERMS
        assert "Seef" in BAHRAINI_KEYTERMS


class TestXAIAdapter:
    """Test xAI adapter initialization."""

    def test_xai_adapter_init(self):
        """XAILLMAdapter should initialize with required params."""
        from hermes_phone.adapters.xai import XAILLMAdapter

        adapter = XAILLMAdapter(
            api_key="test_key",
            model="grok-4.3",
            reasoning_effort="none",
            temperature=0.7,
        )

        assert adapter.api_key == "test_key"
        assert adapter.model == "grok-4.3"
        assert adapter.reasoning_effort == "none"
        assert adapter.temperature == 0.7


class TestElevenLabsAdapter:
    """Test ElevenLabs adapter initialization."""

    def test_elevenlabs_adapter_init(self):
        """ElevenLabsTTSAdapter should initialize with required params."""
        from hermes_phone.adapters.elevenlabs import ElevenLabsTTSAdapter

        adapter = ElevenLabsTTSAdapter(
            api_key="test_key",
            voice_id="test_voice_id",
            model="eleven_flash_v2_5",
            output_format="ulaw_8000",
        )

        assert adapter.api_key == "test_key"
        assert adapter.voice_id == "test_voice_id"
        assert adapter.model == "eleven_flash_v2_5"
        assert adapter.output_format == "ulaw_8000"


class TestTwilioAdapter:
    """Test Twilio adapter initialization."""

    def test_twilio_adapter_init(self):
        """TwilioTelephonyAdapter should initialize with required params."""
        from hermes_phone.adapters.twilio import TwilioTelephonyAdapter

        # Mock WebSocket and client
        class MockWS:
            async def receive_text(self):
                return '{"event": "start", "start": {"streamSid": "test_sid"}}'

            async def send_text(self, msg):
                pass

        adapter = TwilioTelephonyAdapter(
            ws=MockWS(),
            call_sid="CA1234567890",
            twilio_client=None,
        )

        assert adapter.call_sid == "CA1234567890"
        assert adapter.stream_sid == ""
