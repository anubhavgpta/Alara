<p align="center">
  <img src="./alara-banner.jpg" alt="ALARA Banner" width="100%" />
</p>

# ALARA

Ambient Language and Reasoning Assistant for Windows development workflows.

ALARA is a voice-first desktop assistant that captures spoken commands, transcribes speech, classifies intent, and executes actions through local integrations (Windows OS, terminal, browser, and VS Code).

## Architecture

ALARA processes commands through the following sequence:

1. Wake-word detection (`core/wake_word.py`)
2. Audio recording (`core/recorder.py`)
3. Speech transcription (`core/transcriber.py`)
4. Intent classification (`core/intent_engine.py`)
5. Action execution (`core/executor.py`)

## Transcription Pipeline

The transcription layer supports multiple runtime strategies:

- `fast` (default): Deepgram first, Whisper fallback.
- `consensus`: Deepgram and Whisper with agreement scoring.
- `deepgram_only`: Deepgram only, Whisper fallback on API failure.
- `whisper_only`: local Whisper-only path.

Audio preprocessing is configurable and can be tuned for latency:

- `ENABLE_AUDIO_PREPROCESSING` (default: `1`)
- `ENABLE_AUDIO_DENOISE` (default: `0`)
- `ENABLE_AUDIO_TRIM` (default: `1`)

## Repository Structure

```text
alara/
|-- main.py
|-- core/
|   |-- action_registry.py
|   |-- assistant.py
|   |-- audio_preprocessor.py
|   |-- executor.py
|   |-- intent_engine.py
|   |-- normalizer.py
|   |-- pipeline.py
|   |-- prompt_builder.py
|   |-- recorder.py
|   |-- transcriber.py
|   |-- wake_word.py
|   `-- ws_server.py
|-- integrations/
|   |-- browser.py
|   |-- terminal.py
|   |-- vscode.py
|   `-- windows_os.py
|-- ui/
|   |-- alara.svg
|   |-- index.html
|   |-- main.js
|   |-- package.json
|   `-- preload.js
|-- tests/
|   |-- test_intent.py
|   `-- test_week56_integrations.py
|-- requirements.txt
`-- .env.example
```

## Prerequisites

- Windows 10 or Windows 11
- Python 3.11+
- Node.js 18+ (for the Electron overlay)
- API keys for configured providers (Gemini and optional Deepgram)

## Installation

```powershell
git clone https://github.com/yourname/alara.git
cd alara

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Create and edit environment settings:

```powershell
copy .env.example .env
notepad .env
```

Minimum required settings:

- `GEMINI_API_KEY=...`

Common optional settings:

- `GEMINI_MODEL=gemini-2.5-flash`
- `DEEPGRAM_API_KEY=...`
- `DEEPGRAM_MODEL=nova-2`
- `STT_STRATEGY=fast`
- `WHISPER_MODEL=small.en`
- `WHISPER_DEVICE=cpu`
- `WHISPER_COMPUTE_TYPE=int8`

## Running ALARA

Backend CLI modes:

```powershell
.venv\Scripts\activate
python -m alara.main --test-stt
python -m alara.main --test-wake-word
python -m alara.main --test-intent
python -m alara.main --test-full
python -m alara.main --ui
python -m alara.main
```

Electron overlay (in a second terminal):

```powershell
cd ui
npm install
npm start
```

## Testing

Run the Python test suite:

```powershell
python -m pytest -q
```

Run the intent benchmark directly:

```powershell
python -m tests.test_intent
```

## UI Overlay

The Electron overlay is implemented in `ui/` and communicates with the Python backend over WebSocket (`ws://localhost:8765`).

Current overlay features:

- Global hotkey toggle
- Text command submission
- Push-to-listen control
- Status transitions (`idle`, `listening`, `processing`)
- Real-time action results

## Scope Status

The repository currently includes a functional implementation for build plan work through Weeks 1-6, with the wake-word pipeline, transcription, intent engine, core integrations, and Electron overlay active.
