"""
alara/main.py

Entry point for ALARA.
Run with: python -m alara.main

For development/testing, use the CLI flags:
  --test-stt        Record one command and print transcription (no wake word needed)
  --test-intent     Type a command and see the parsed intent JSON
  --test-full       Type a command and run the full pipeline
  --test-wake-word  Listen for ~30 seconds and count wake word detections
"""

import argparse
import sys
import time
from dotenv import load_dotenv
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

load_dotenv()  # load .env before any imports that read env vars

console = Console()


def print_banner():
    text = Text()
    text.append("ALARA\n", style="bold bright_magenta")
    text.append("Ambient Language & Reasoning Assistant\n", style="bright_white")
    text.append("Voice-First OS for Windows  ·  v0.1.0", style="dim")
    console.print(Panel(text, border_style="bright_magenta", padding=(1, 4)))


def run_full():
    """Start the full wake-word pipeline."""
    from alara.core.pipeline import AlaraPipeline
    pipeline = AlaraPipeline()
    pipeline.start()


def test_stt():
    """Record one command and print transcription. No wake word needed."""
    from alara.core.recorder import AudioRecorder
    from alara.core.transcriber import Transcriber

    console.print("[yellow]Speak now...[/yellow]")
    recorder = AudioRecorder()
    wav_bytes = recorder.record()

    console.print("[yellow]Transcribing...[/yellow]")
    transcriber = Transcriber()
    text = transcriber.transcribe(wav_bytes)

    console.print(f"\n[bold green]Transcription:[/bold green] {text}\n")


def test_intent():
    """Type a command and see the parsed intent JSON."""
    from alara.core.intent_engine import IntentEngine
    import json

    engine = IntentEngine()
    command = input("Enter a voice command to test: ").strip()
    action = engine.parse(command)

    console.print(f"\n[bold green]Action:[/bold green] {action.action}")
    console.print(f"[bold green]Params:[/bold green] {json.dumps(action.params, indent=2)}")
    console.print(f"[bold green]Confidence:[/bold green] {action.confidence:.2f}\n")


def test_full():
    """Type a command and run the full pipeline (intent + executor)."""
    from alara.core.intent_engine import IntentEngine
    from alara.core.executor import Executor

    engine = IntentEngine()
    executor = Executor()

    command = input("Enter a voice command to test: ").strip()
    action = engine.parse(command)
    result = executor.execute(action)

    console.print(f"\n[bold green]Result:[/bold green] {result}\n")


def test_wake_word():
    """Test wake word detection. Listens for ~30 seconds and prints detections."""
    from alara.core.wake_word import WakeWordDetector

    detection_count = [0]  # Use list to allow modification in nested function

    def on_detected():
        detection_count[0] += 1
        console.print(f"[bold bright_green]✓ Wake word detected! #{detection_count[0]}[/bold bright_green]")

    console.print("[yellow]Starting wake word detector...[/yellow]")
    console.print("[dim]Speak naturally or make noise to trigger detection[/dim]")
    console.print("[dim](listening for ~30 seconds)[/dim]\n")

    detector = WakeWordDetector(on_detected=on_detected)
    detector.start()

    try:
        time.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        detector.stop()
        console.print(f"\n[bold green]Detections:[/bold green] {detection_count[0]}")
        console.print("[dim]Test complete[/dim]\n")


def main():
    print_banner()

    parser = argparse.ArgumentParser(description="ALARA - Voice-First OS")
    parser.add_argument("--test-stt",       action="store_true", help="Test STT pipeline")
    parser.add_argument("--test-intent",    action="store_true", help="Test intent engine")
    parser.add_argument("--test-full",      action="store_true", help="Test full pipeline by typing")
    parser.add_argument("--test-wake-word", action="store_true", help="Test wake word detection")
    args = parser.parse_args()

    if args.test_stt:
        test_stt()
    elif args.test_intent:
        test_intent()
    elif args.test_full:
        test_full()
    elif args.test_wake_word:
        test_wake_word()
    else:
        run_full()


if __name__ == "__main__":
    main()
