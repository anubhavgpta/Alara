"""
alara/core/wake_word.py

Listens continuously on the default microphone for the wake word.
Uses OpenWakeWord for local, CPU-efficient detection.
Fires a callback when the wake word is detected.
"""

import threading
import numpy as np
import sounddevice as sd
from openwakeword.model import Model
from loguru import logger
import os


SAMPLE_RATE = 16000       # Hz — openwakeword requires 16kHz
CHUNK_SIZE = 1280         # samples per chunk (~80ms at 16kHz)
CHANNELS = 1


class WakeWordDetector:
    """
    Runs in a background thread, continuously listening for the wake word.
    Calls on_detected() when confidence exceeds the threshold.

    Usage:
        detector = WakeWordDetector(on_detected=my_callback)
        detector.start()
        ...
        detector.stop()
    """

    def __init__(self, on_detected: callable, threshold: float = None):
        self.on_detected = on_detected
        self.threshold = threshold or float(os.getenv("WAKE_WORD_THRESHOLD", 0.5))
        self.wake_word = os.getenv("WAKE_WORD", "hey_jarvis")
        self._running = False
        self._thread = None
        self._model = None
        self._use_legacy_detector = False  # Flag for fallback mode

    def _load_model(self):
        """Load the OpenWakeWord model. Falls back to simple volume-based detection."""
        logger.info(f"Loading wake word model: {self.wake_word}")
        try:
            # Try to load OpenWakeWord
            self._model = Model(
                wakeword_models=[self.wake_word],
                enable_speex_noise_suppression=True,
            )
            self._use_legacy_detector = False
            logger.success("Wake word model loaded (OpenWakeWord)")
        except Exception as e:
            logger.warning(
                f"OpenWakeWord unavailable ({type(e).__name__}), "
                f"falling back to volume-based detector"
            )
            self._use_legacy_detector = True

    def _listen_loop(self):
        """Main listening loop — runs in background thread."""
        if self._use_legacy_detector:
            self._listen_loop_volume_based()
        else:
            self._listen_loop_ml_based()

    def _listen_loop_ml_based(self):
        """ML-based wake word detection (OpenWakeWord)."""
        logger.info(f"Wake word detector active (threshold={self.threshold})")

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        ) as stream:
            while self._running:
                audio_chunk, _ = stream.read(CHUNK_SIZE)
                audio_np = np.frombuffer(audio_chunk, dtype=np.int16)

                # Feed chunk to model and get predictions
                predictions = self._model.predict(audio_np)

                for model_name, confidence in predictions.items():
                    if confidence >= self.threshold:
                        logger.info(
                            f"Wake word detected! [{model_name}] confidence={confidence:.2f}"
                        )
                        # Reset model state to avoid double-firing
                        self._model.reset()
                        # Fire callback (non-blocking)
                        threading.Thread(
                            target=self.on_detected, daemon=True
                        ).start()
                        break

    def _listen_loop_volume_based(self):
        """
        Fallback: Simple volume-based activation.
        Detects loud speech bursts as wake word trigger.
        Used when OpenWakeWord is unavailable (Windows/TFLite issue).
        """
        logger.info("Wake word detector active (volume-based, Windows fallback)")
        
        # These settings detect speech more reliably
        volume_threshold = 1000  # RMS threshold for speech detection (lowered for sensitivity)
        min_duration_chunks = 2  # ~160ms of speech needed (faster trigger)
        silence_limit = 10  # Reset after 10 chunks of silence

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        ) as stream:
            silent_chunks = 0
            speech_chunks = 0

            while self._running:
                audio_chunk, _ = stream.read(CHUNK_SIZE)
                audio_np = np.frombuffer(audio_chunk, dtype=np.int16).astype(float)

                # Calculate RMS (root mean square) as volume indicator
                rms = np.sqrt(np.mean(audio_np ** 2))

                if rms > volume_threshold:
                    # Speech detected
                    speech_chunks += 1
                    silent_chunks = 0

                    if speech_chunks >= min_duration_chunks:
                        logger.info(f"Voice detected! (RMS={rms:.0f})")
                        speech_chunks = 0  # Reset to avoid repeated fires
                        threading.Thread(
                            target=self.on_detected, daemon=True
                        ).start()
                else:
                    # Silence
                    silent_chunks += 1
                    if silent_chunks > silence_limit:
                        speech_chunks = 0  # Reset counter

    def start(self):
        """Start listening in a background thread."""
        if self._running:
            logger.warning("WakeWordDetector already running")
            return
        try:
            self._load_model()
            self._running = True
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()
            logger.success("WakeWordDetector started")
        except Exception as e:
            logger.error(f"Failed to start wake word detector: {e}")
            raise

    def stop(self):
        """Stop the listening thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("WakeWordDetector stopped")
