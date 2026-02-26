"""
alara/core/transcriber.py

Local speech-to-text using faster-whisper.
"""

import io
import os
import wave

import numpy as np
from faster_whisper import WhisperModel
from loguru import logger


class Transcriber:
    """
    Wraps faster-whisper for local speech-to-text.
    """

    def __init__(self):
        model_size = os.getenv("WHISPER_MODEL", "tiny.en")
        device = os.getenv("WHISPER_DEVICE", "cpu")
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

        logger.info(
            f"Loading Whisper model '{model_size}' "
            f"on {device.upper()} ({compute_type})..."
        )
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )
        self.beam_size = 1 if device == "cpu" else 5
        logger.success(f"Whisper ready model={model_size} device={device}")

    def transcribe(self, wav_bytes: bytes) -> str:
        """Transcribe WAV bytes to text."""
        if not wav_bytes:
            return ""

        try:
            audio_np = self._wav_to_float32(wav_bytes)
            segments, _ = self.model.transcribe(
                audio_np,
                language="en",
                beam_size=self.beam_size,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )

            transcript = " ".join(seg.text.strip() for seg in segments).strip()
            if transcript:
                logger.info(f"Transcription: '{transcript}'")
            else:
                logger.warning("Whisper returned empty transcript")
            return transcript
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return ""

    def _wav_to_float32(self, wav_bytes: bytes) -> np.ndarray:
        """Convert WAV bytes to float32 numpy array in [-1, 1]."""
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        audio_int16 = np.frombuffer(raw, dtype=np.int16)
        return audio_int16.astype(np.float32) / 32768.0
