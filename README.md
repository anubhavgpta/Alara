# ALARA - Ambient Language & Reasoning Assistant

> Voice-first operating workflow for Windows. Control your computer through natural language commands.

---

## Week 1-2 Goals

By the end of Week 2 you should be able to:
1. Say a command and see accurate transcription in under 400ms.
2. Type a command and see the correct intent JSON.
3. Run the full pipeline end-to-end (even if some executors are stubs).

---

## Setup

### 1. Prerequisites

- Windows 10/11
- Python 3.11+
- NVIDIA GPU (recommended for faster speech-to-text inference)
- No paid API keys required for the intent engine

One-time installs:

**Ollama** (local model runtime)
```powershell
# 1. Download and install from https://ollama.com/download
# 2. Pull the model (one-time download)
ollama pull llama3.1
# Ollama runs on http://localhost:11434
```

**CUDA Toolkit** (if not already installed)
```
https://developer.nvidia.com/cuda-downloads
```

### 2. Clone and install

```powershell
git clone https://github.com/yourname/alara.git
cd alara

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (for browser control)
playwright install chromium
```

### 3. Configure

```powershell
# Copy env template
copy .env.example .env

# Review defaults
notepad .env
```

### 4. Run

```powershell
# Activate venv if not already
.venv\Scripts\activate

# Test STT only
python -m alara.main --test-stt

# Test intent engine only
python -m alara.main --test-intent

# Test full pipeline by typing
python -m alara.main --test-full

# Run wake-word pipeline
python -m alara.main
```

---

## Project Structure

```
alara/
|-- main.py                    # Entry point and CLI flags
|-- core/
|   |-- wake_word.py           # Wake word detection (OpenWakeWord)
|   |-- recorder.py            # Microphone capture
|   |-- transcriber.py         # Speech-to-text integration
|   |-- intent_engine.py       # Ollama intent parsing + schema normalization -> JSON
|   |-- executor.py            # Action dispatch to integrations
|   `-- pipeline.py            # End-to-end orchestration
|-- integrations/
|   |-- windows_os.py          # App/window/file/system control
|   |-- terminal.py            # Windows Terminal / PowerShell actions
|   |-- browser.py             # Browser control via Playwright
|   `-- vscode.py              # VS Code control
|-- memory/                    # Local memory layer
|-- utils/                     # Shared utilities
|-- requirements.txt
`-- .env.example
```

---

## Week 3-4 Implementation: Intent Engine

### Implementation Summary

The intent classification engine has been updated to an **Ollama-first** design.
Classification decisions are produced by the local LLM, and the resulting output is then normalized into ALARA's strict action schema.

### Detailed Changes

**1. Ollama-first classification path**
- The engine uses Ollama `/api/chat` for intent classification.
- Prompting is constrained to ALARA's supported action set.
- The response contract requires a single JSON object with `action`, `params`, and `confidence`.
- Model options were tuned for consistent structure (`temperature=0.0`).

**2. Formal action schema validation**
- All outputs pass through a Pydantic `Action` model.
- Unsupported action labels are rejected and safely mapped to `unknown`.
- Confidence values are bounded to `[0.0, 1.0]`.

**3. Output canonicalization layer**
- The model may return valid intent with inconsistent field names (for example, `app` instead of `app_name`, or `file` instead of `path`/`query`).
- Canonicalization standardizes these variants to ALARA's schema.
- Common LLM output variants (including non-schema action names) are normalized to valid ALARA actions when the command context is unambiguous.
- Canonicalization aligns output format and schema semantics; intent generation remains Ollama-based.

**4. Robust JSON recovery and retries**
- Multi-stage JSON extraction handles minor response formatting noise.
- Retries with backoff handle transient Ollama errors.
- Unrecoverable failures return `unknown` with a reason string.

**5. Improved observability**
- Parse attempts and final normalized actions are logged.
- Logs include action, parameters, and confidence for diagnosis.

### Running the test suite

```powershell
# Standard test run
python -m tests.test_intent
```

The suite:
- Runs 50 commands across 8 categories.
- Reports aggregate and category-level accuracy.
- Exports detailed results to `test_results.json`.
- Compares results against the 90% target.

For Windows console encoding compatibility during direct inline runs:

```powershell
$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -c "from tests.test_intent import IntentTestSuite; s=IntentTestSuite(); r=s.run_all_tests(); print('ACCURACY', r['accuracy'])"
```

### Test categories

The suite covers 50 commands:
- App Control (10)
- Terminal Commands (8)
- File Operations (7)
- Browser Operations (8)
- VS Code Operations (5)
- Window Management (4)
- System Operations (4)
- Unknown Commands (4)

### Target and measured accuracy

- Goal: **90%+** classification accuracy.
- Measured result on **February 26, 2026**: **50/50 passed (100.0%)**.
- Benchmark method: `tests/test_intent.py` standardized evaluation set.

### Current intent engine architecture

The current engine includes:
- Local LLM inference through Ollama.
- Strict schema validation through Pydantic.
- Output canonicalization into ALARA action format.
- JSON recovery and retry handling.
- Safe fallback behavior with `unknown` action responses.

---

## Week 1-2 Test Checklist

- [ ] `python -m alara.main --test-stt` transcribes speech accurately.
- [ ] Transcription latency is under 400ms end-to-end.
- [ ] `python -m alara.main --test-intent "open VS Code"` returns `{"action": "open_app", ...}`.
- [ ] `python -m alara.main --test-intent "run git status in terminal"` returns `{"action": "run_command", ...}`.

---

## Notes

- Privacy: In v1, audio may be sent to external STT services depending on transcriber configuration. Use local STT for fully local operation.
- Wake word: OpenWakeWord includes built-in models such as `hey_jarvis`, `alexa`, and `hey_mycroft`.
- Platform scope: Windows-specific integrations are intentionally used for this version.
