"""
alara/core/pipeline.py

The main Alara pipeline.
Wires together: WakeWord → Recorder → Transcriber → IntentEngine → Executor

This is the heart of the application.
"""

import time
from loguru import logger
from alara.core.wake_word import WakeWordDetector
from alara.core.recorder import AudioRecorder
from alara.core.transcriber import Transcriber
from alara.core.intent_engine import IntentEngine
from alara.core.executor import Executor


class AlaraPipeline:
    """
    Orchestrates the full voice command pipeline.

    Flow:
        [Wake Word Detected]
            → Record audio until silence
            → Transcribe with Deepgram
            → Parse intent with GPT-4o-mini
            → Execute with appropriate integration

    Usage:
        pipeline = AlaraPipeline()
        pipeline.start()   # blocks forever (Ctrl+C to quit)
    """

    def __init__(self):
        logger.info("Initializing ALARA pipeline...")
        self.recorder = AudioRecorder()
        self.transcriber = Transcriber()
        self.intent_engine = IntentEngine()
        self.executor = Executor()
        self._is_listening = False

        # Wake word detector fires _on_wake_word when triggered
        self.wake_detector = WakeWordDetector(
            on_detected=self._on_wake_word
        )
        logger.success("ALARA pipeline initialized")

    def _on_wake_word(self):
        """Called by WakeWordDetector when wake word is heard."""
        if self._is_listening:
            logger.debug("Already processing a command — ignoring wake word")
            return

        self._is_listening = True
        try:
            self._process_command()
        finally:
            self._is_listening = False

    def _process_command(self):
        """Run the full pipeline for one voice command."""
        t0 = time.perf_counter()

        # Step 1: Record
        wav_bytes = self.recorder.record()
        if not wav_bytes:
            logger.warning("No audio captured — aborting")
            return
        t1 = time.perf_counter()

        # Step 2: Transcribe
        transcription = self.transcriber.transcribe(wav_bytes)
        if not transcription:
            logger.warning("Empty transcription — aborting")
            return
        t2 = time.perf_counter()

        # Step 3: Parse intent
        action = self.intent_engine.parse(transcription)
        t3 = time.perf_counter()

        # Step 4: Execute
        result = self.executor.execute(action)
        t4 = time.perf_counter()

        # Log timing breakdown
        logger.info(
            f"Pipeline timing: "
            f"record={t1-t0:.2f}s | "
            f"transcribe={t2-t1:.2f}s | "
            f"intent={t3-t2:.2f}s | "
            f"execute={t4-t3:.2f}s | "
            f"total={t4-t0:.2f}s"
        )
        logger.info(f"Result: {result}")

    def start(self):
        """Start the pipeline. Blocks until KeyboardInterrupt."""
        logger.success("ALARA is awake. Give a voice command.")
        logger.info("Press Ctrl+C to stop.\n")

        # Try to start wake word detector; fall back to direct listening if unavailable
        try:
            self.wake_detector.start()
        except Exception as e:
            logger.warning(f"Wake word detection unavailable ({e}), using direct listening")
            # Start direct listening loop instead
            self._direct_listening_loop()
            return

        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("\nShutting down ALARA...")
            self.wake_detector.stop()

    def _direct_listening_loop(self):
        """Listen for voice commands continuously without wake word detection."""
        try:
            while True:
                logger.info("\nListening for command (say something)...")
                self._on_wake_word()
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("\nShutting down ALARA...")
            logger.success("ALARA stopped cleanly.")
