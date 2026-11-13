"""
Speech-to-Text (STT) Adapters for Customer Support Assistant.
Complies with Specification Section 1.5, 8.1, 13 (Voice & Multilingual), and SpeechPort.
Supports Groq Whisper API (whisper-large-v3) and deterministic offline Mock STT.
"""

from typing import Optional
import os
import io
import json
import logging

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

logger = logging.getLogger(__name__)


class GroqWhisperAdapter:
    """
    Production Groq Whisper STT adapter.
    Transcribes English, Tamil, and Tanglish customer voice notes using whisper-large-v3.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "whisper-large-v3"):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "").strip()
        self.model = model
        if AsyncOpenAI and self.api_key:
            self._client = AsyncOpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=self.api_key
            )
        else:
            self._client = None

    async def transcribe(self, audio_bytes: bytes, content_type: str = "audio/ogg") -> str:
        if not self._client:
            raise RuntimeError("Groq Whisper STT requires GROQ_API_KEY to be set in environment.")

        # Determine extension from content_type
        ext = "ogg" if "ogg" in content_type else "wav" if "wav" in content_type else "mp3"
        filename = f"voice_note.{ext}"

        file_tuple = (filename, io.BytesIO(audio_bytes), content_type)
        transcript = await self._client.audio.transcriptions.create(
            file=file_tuple,
            model=self.model,
            prompt=(
                "Transcribe the audio verbatim in the language and script spoken; do not translate or paraphrase. "
                "For Tamil-English code-switching (Tanglish), preserve Tamil words as spoken in Latin script "
                "when the speaker uses Latin transliteration, and keep English words in English. "
                "Preserve names, product names, order IDs, and numbers exactly."
            ),
            response_format="text"
        )
        return str(transcript).strip()


class MockSpeechAdapter:
    """
    Deterministic offline STT engine for unit testing, CI/CD, and offline demonstration.
    Accurately maps synthetic audio waveforms or payload hints to English, Tamil, and Tanglish text.
    """

    def __init__(self):
        # Known synthetic audio signatures / mapping for tests
        self.signatures = {
            b"AUDIO_P1041_PRICE": "What is the price of product P1041?",
            b"AUDIO_P1041_SPECS": "Tell me the battery life and specs for Pulse Buds 141",
            b"AUDIO_ORD_1029_STATUS": "Where is my order ORD-1029?",
            b"AUDIO_ORD_9001_STATUS": "Where is my order ORD-9001?",
            b"AUDIO_ORD_101_REFUND": "I want a refund for my order ORD-101",
            b"AUDIO_TAMIL_PRICE": "Pulse Buds 141 விலை என்ன?",
            b"AUDIO_TANGLISH_ORDER": "Enna order ORD-1029 vandhurucha? Status sollunga",
        }

    async def transcribe(self, audio_bytes: bytes, content_type: str = "audio/ogg") -> str:
        if not audio_bytes:
            return ""

        # Check exact known test signatures
        for sig, transcript in self.signatures.items():
            if sig in audio_bytes:
                return transcript

        # If audio_bytes is JSON containing a simulated transcript hint (for test payloads)
        try:
            payload = json.loads(audio_bytes.decode("utf-8"))
            if isinstance(payload, dict) and "simulated_transcript" in payload:
                return payload["simulated_transcript"]
        except Exception:
            pass

        # Unknown/real audio must not be mislabeled as a canned transcript.
        return ""
