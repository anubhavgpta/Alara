"""
alara/core/recorder.py

Captures audio from the microphone after wake word detection.
Stops recording after a configurable silence timeout.
Returns raw PCM bytes ready to send to Deepgram.
"""

import io
import wave
import numpy as np
import sounddevice as sd
from loguru import logger
import os


SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024         # samples per read
SILENCE_THRESHOLD = 500   # RMS below this = silence
MIN_RECORDING_MS = 300    # always record at least 300ms after wake word


class AudioRecorder:
    """
    Records a single voice command after the wake word fires.

    Returns WAV bytes when silence is detected (or max duration reached).

    Usage:
        recorder = AudioRecorder()
        wav_bytes = recorder.record()   # blocks until done
    """

    def __init__(self):
        self.silence_timeout_ms = int(os.getenv("SILENCE_TIMEOUT_MS", 1500))
        self.max_duration_s = 15  # hard cap — no command should be longer

    def _is_silent(self, audio_chunk: np.ndarray) -> bool:
        """Returns True if the chunk's RMS energy is below silence threshold."""
        rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))
        return rms < SILENCE_THRESHOLD

    def record(self) -> bytes:
        """
        Record audio until silence is detected.
        Returns WAV-encoded bytes.
        """
        logger.info("Recording command...")
        frames = []
        silent_chunks = 0
        total_chunks = 0

        silence_chunks_needed = int(
            (self.silence_timeout_ms / 1000) * SAMPLE_RATE / CHUNK_SIZE
        )
        max_chunks = int(self.max_duration_s * SAMPLE_RATE / CHUNK_SIZE)
        min_chunks = int((MIN_RECORDING_MS / 1000) * SAMPLE_RATE / CHUNK_SIZE)

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        ) as stream:
            while total_chunks < max_chunks:
                chunk, _ = stream.read(CHUNK_SIZE)
                audio_np = np.frombuffer(chunk, dtype=np.int16)
                frames.append(audio_np.copy())
                total_chunks += 1

                if total_chunks < min_chunks:
                    continue  # always record minimum duration

                if self._is_silent(audio_np):
                    silent_chunks += 1
                    if silent_chunks >= silence_chunks_needed:
                        logger.debug(
                            f"Silence detected after {total_chunks} chunks "
                            f"({total_chunks * CHUNK_SIZE / SAMPLE_RATE:.1f}s)"
                        )
                        break
                else:
                    silent_chunks = 0  # reset on any speech

        if not frames:
            logger.warning("No audio captured")
            return b""

        # Encode to WAV bytes
        audio_data = np.concatenate(frames, axis=0)
        return self._to_wav_bytes(audio_data)

    def _to_wav_bytes(self, audio_np: np.ndarray) -> bytes:
        """Convert numpy audio array to WAV bytes."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit = 2 bytes
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_np.tobytes())
        buf.seek(0)
        return buf.read()
