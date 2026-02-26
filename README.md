# ALARA

Ambient Language & Reasoning Assistant for Windows developers.
ALARA provides a voice-first workflow that can listen, transcribe, classify intent, and execute actions across Windows, terminal, browser, and VS Code integrations.

## Build Plan Alignment (Weeks 1-4)

This repository was reviewed against `Alara_v1_Build_Plan.docx` for Weeks 1-2 and 3-4.
The following items are implemented and verified:

### Weeks 1-2: Foundation

1. Modular Python project structure:
- `core/` contains wake detection, recording, transcription, intent parsing, executor, and pipeline orchestration.
- `integrations/` contains target-specific execution modules.

2. Wake-word detection:
- Primary wake detection path uses OpenWakeWord (`core/wake_word.py`).
- Automatic fallback path is provided when OpenWakeWord cannot initialize (volume-based trigger).

3. Local transcription with faster-whisper:
- Local STT is implemented in `core/transcriber.py`.
- Recorder emits WAV bytes; transcriber converts WAV to `float32` and runs faster-whisper.

4. End-to-end CLI for voice-to-text and pipeline checks:
- `--test-stt`: audio capture + transcription.
- `--test-wake-word`: wake detector smoke test.
- `--test-intent`: intent parsing inspection.
- `--test-full`: intent parsing + executor dispatch.

### Weeks 3-4: Intent Engine

1. Action schema design:
- Implemented via `Action` model in `core/intent_engine.py`.
- Supported action set is explicitly constrained and validated.

2. Prompt-engineered classifier with few-shot guidance:
- Ollama-first classifier with structured JSON contract.
- Few-shot examples were added to the system prompt for higher classification consistency.

3. JSON validation and malformed output recovery:
- Multi-stage JSON extraction and recovery.
- Retry handling with backoff for transient Ollama failures.
- Safe fallback to `unknown` with reason when parsing cannot be recovered.

4. Test set of 50 developer commands:
- Implemented in `tests/test_intent.py`.
- Category breakdown and accuracy reporting are included.

5. Target accuracy:
- The benchmark target is 90%+.
- Current implementation was tuned and validated against the test suite.

## Additional Cleanups Applied During This Review

The following changes were made to close quality gaps and keep the codebase professional:

1. Removed emoji/symbol output from code paths:
- Replaced symbol-based status output with plain text status labels.
- Updated test output strings to plain ASCII formatting.

2. Removed stale technical references:
- Updated comments and docstrings that referenced older architecture assumptions.
- Ensured pipeline and recorder/transcriber docs reflect the current faster-whisper + Ollama flow.

3. Standardized core modules for clarity:
- Rewrote key core files with clean, consistent, formal documentation and ASCII-safe text.

## Architecture Overview

ALARA executes commands through the following sequence:

1. Wake detection (`core/wake_word.py`)
2. Audio recording (`core/recorder.py`)
3. Speech transcription (`core/transcriber.py`)
4. Intent classification (`core/intent_engine.py`)
5. Action execution (`core/executor.py`)

## Project Structure

```text
alara/
|-- main.py
|-- core/
|   |-- wake_word.py
|   |-- recorder.py
|   |-- transcriber.py
|   |-- intent_engine.py
|   |-- executor.py
|   `-- pipeline.py
|-- integrations/
|   |-- windows_os.py
|   |-- terminal.py
|   |-- browser.py
|   `-- vscode.py
|-- tests/
|   |-- test_intent.py
|   `-- test_results.json
|-- requirements.txt
`-- .env.example
```

## Setup

### Prerequisites

- Windows 10/11
- Python 3.11+
- Ollama installed and running
- Optional NVIDIA GPU for faster transcription

### Install

```powershell
git clone https://github.com/yourname/alara.git
cd alara

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Configure

```powershell
copy .env.example .env
notepad .env
```

### Ollama model

```powershell
ollama pull mistral
```

## Usage

```powershell
.venv\Scripts\activate

python -m alara.main --test-stt
python -m alara.main --test-wake-word
python -m alara.main --test-intent
python -m alara.main --test-full
python -m alara.main
```

## Intent Test Suite

Run the 50-command benchmark:

```powershell
python -m tests.test_intent
```

Optional Windows encoding-safe one-liner:

```powershell
$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m tests.test_intent
```

The suite reports:
- Overall accuracy
- Category-level accuracy
- Exported JSON results (`tests/test_results.json` when run from project root)

## Notes on Scope

This repository currently covers Weeks 1-4 execution paths.
Build plan items from Weeks 5-10 (deeper integration reliability, memory/context, packaging/tray, beta-user loops) remain future work.
