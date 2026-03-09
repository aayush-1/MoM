from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile

from googleapiclient.discovery import build

from config import SPEECH_LANGUAGE_CODES
from google_docs_service import get_credentials

logger = logging.getLogger(__name__)

_speech_service = None


def _get_speech_service():
    global _speech_service
    if _speech_service is None:
        creds = get_credentials()
        _speech_service = build("speech", "v1", credentials=creds)
    return _speech_service


def transcribe_audio(ogg_path: str) -> str:
    """Convert an .ogg voice note to WAV and transcribe via Google Speech-to-Text."""
    wav_path = ogg_path.rsplit(".", 1)[0] + ".wav"

    try:
        subprocess.run(
            [
                "ffmpeg", "-i", ogg_path,
                "-f", "wav", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1",
                wav_path, "-y",
            ],
            check=True,
            capture_output=True,
        )

        with open(wav_path, "rb") as f:
            audio_content = base64.b64encode(f.read()).decode("utf-8")

        service = _get_speech_service()
        body = {
            "config": {
                "encoding": "LINEAR16",
                "sampleRateHertz": 16000,
                "languageCode": SPEECH_LANGUAGE_CODES[0],
                "alternativeLanguageCodes": SPEECH_LANGUAGE_CODES[1:],
            },
            "audio": {
                "content": audio_content,
            },
        }
        response = service.speech().recognize(body=body).execute()

        results = response.get("results", [])
        if not results:
            logger.warning("Speech-to-Text returned no results")
            return "[could not transcribe]"

        transcript = " ".join(
            r["alternatives"][0]["transcript"]
            for r in results
            if r.get("alternatives")
        )
        return transcript.strip() or "[could not transcribe]"

    except subprocess.CalledProcessError:
        logger.exception("ffmpeg conversion failed")
        raise
    except Exception:
        logger.exception("Transcription failed")
        raise
    finally:
        for path in [ogg_path, wav_path]:
            try:
                os.remove(path)
            except OSError:
                pass
