"""
alara/core/transcriber.py

Local speech-to-text using faster-whisper.
Runs entirely on your NVIDIA GPU via CUDA — no API key, no internet required.

Model size tradeoffs (set in .env → WHISPER_MODEL):
  tiny.en   ~75MB   fastest, less accurate
  base.en   ~145MB  good balance for dev             ← recommended start
  small.en  ~465MB  noticeably better accuracy
  medium.en ~1.5GB  very accurate, still real-time on GPU
  large-v3  ~3GB    best accuracy, slightly slower
"""

import io
import os
import numpy as np
from faster_whisper import WhisperModel
from loguru import logger


class Transcriber:
    """
    Wraps faster-whisper for local, GPU-accelerated speech-to-text.

    Usage:
        transcriber = Transcriber()
        text = transcriber.transcribe(wav_bytes)

    First run downloads the model (~145MB for base.en) and caches it.
    Every run after that loads from cache instantly.
    """

    def __init__(self):
        model_size    = os.getenv("WHISPER_MODEL", "tiny.en")
        device        = os.getenv("WHISPER_DEVICE", "cpu")
        compute_type  = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

        logger.info(
            f"Loading Whisper model '{model_size}' "
            f"on {device.upper()} ({compute_type})..."
        )
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )
        self.beam_size = 1 if device == "cpu" else 5  # Faster on CPU, better on GPU
        logger.success(f"Whisper ready — model={model_size} device={device}")

    def transcribe(self, wav_bytes: bytes) -> str:
        """
        Transcribe WAV bytes → text string.
        Returns empty string on failure or silence.
        """
        if not wav_bytes:
            return ""

        try:
            audio_np = self._wav_to_float32(wav_bytes)

            segments, _ = self.model.transcribe(
                audio_np,
                language="en",
                beam_size=self.beam_size,        # 1 for CPU speed, 5 for GPU accuracy
                vad_filter=True,                 # skip silent segments automatically
                vad_parameters=dict(min_silence_duration_ms=300),
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
        """
        Convert WAV bytes → float32 numpy array in range [-1.0, 1.0].
        faster-whisper expects 16kHz mono float32 — which recorder.py produces.
        """
        import wave
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        audio_int16 = np.frombuffer(raw, dtype=np.int16)
        return audio_int16.astype(np.float32) / 32768.0
