# ALARA — Ambient Language & Reasoning Assistant

> Voice-First OS for Windows. Control your entire computer just by talking.

---

## Week 1–2 Goals

By the end of Week 2 you should be able to:
1. Say a command and see the accurate transcription in < 400ms
2. Type a command and see the correct intent JSON parsed out
3. Have the full pipeline wired end-to-end (even if executors are stubs)

---

## Setup

### 1. Prerequisites

- Windows 10/11
- Python 3.11+
- NVIDIA GPU (for fast Whisper via CUDA)
- **No paid API keys needed — 100% local and free**

**One-time installs:**

**Ollama** (runs llama3.1 locally):
```powershell
# 1. Download and install from https://ollama.com/download
# 2. Pull the model (~4.7GB, one-time download)
ollama pull llama3.1
# Ollama now runs silently in the background on http://localhost:11434
```

**CUDA Toolkit** (if not already installed):
```
https://developer.nvidia.com/cuda-downloads
```

### 2. Clone & Install

```powershell
git clone https://github.com/yourname/alara.git
cd alara

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (for browser control later)
playwright install chromium
```

### 3. Configure

```powershell
# Copy the example env file (no API keys needed!)
copy .env.example .env

# Open and review — defaults work out of the box
notepad .env
```

### 4. Run

```powershell
# Activate venv if not already
.venv\Scripts\activate

# Test STT only (speak into mic, see transcription)
python -m alara.main --test-stt

# Test intent engine (type commands, see parsed JSON)
python -m alara.main --test-intent

# Test full pipeline by typing (no mic needed)
python -m alara.main --test-full

# Run the full wake-word pipeline
python -m alara.main
```

---

## Project Structure

```
alara/
├── main.py                    # Entry point + CLI flags
├── core/
│   ├── wake_word.py           # Always-on wake word detection (OpenWakeWord)
│   ├── recorder.py            # Mic capture after wake word
│   ├── transcriber.py         # Deepgram STT
│   ├── intent_engine.py       # GPT-4o-mini intent parsing → JSON
│   ├── executor.py            # Dispatches actions to integrations
│   └── pipeline.py            # Wires everything together
├── integrations/
│   ├── windows_os.py          # App, window, file, system control
│   ├── terminal.py            # Windows Terminal / PowerShell
│   ├── browser.py             # Chrome/Edge via Playwright CDP
│   └── vscode.py              # VS Code via CLI + keyboard
├── memory/                    # (Week 9) Local SQLite memory
├── utils/                     # Shared helpers
├── requirements.txt
└── .env.example
```

---

## Week 1–2 Test Checklist

Run through these to validate your setup:

- [ ] `python -m alara.main --test-stt` transcribes speech accurately
- [ ] Transcription latency is under 400ms end-to-end
- [ ] `python -m alara.main --test-intent "open VS Code"` returns `{"action": "open_app", ...}`
- [ ] `python -m alara.main --test-intent "run git status in terminal"` returns `{"action": "run_command", ...}`
- [ ] `python -m alara.main --test-full` runs the full pipeline without errors
- [ ] `python -m alara.main` starts and waits for wake word

---

## Week 3–4 Preview: Intent Test Suite

Once Week 1–2 is working, create `tests/test_intent.py` with 50 real commands
and run it to measure your classification accuracy. Target: 90%+.

---

## Notes

- **Privacy**: In v1, audio is sent to Deepgram (their servers). To go fully local, swap `transcriber.py` to use `faster-whisper`.
- **Wake word**: OpenWakeWord ships with `hey_jarvis`, `alexa`, `hey_mycroft`. A custom `hey_alara` model can be trained later — see OpenWakeWord docs.
- **Windows only**: `pywinauto` and `win32api` are Windows-exclusive. This is intentional.
