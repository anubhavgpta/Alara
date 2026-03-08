<p align="center">
  <img src="./alara-banner.jpg" alt="ALARA Banner" width="100%" />
</p>

# ALARA
**Ambient Language & Reasoning Assistant**

ALARA is an agentic desktop AI platform for Windows that transforms natural language goals into executable tasks on a real machine. It implements a complete autonomous loop: goal understanding, two-pass structured planning, capability-routed execution, programmatic verification, and LLM-powered adaptive error recovery — all backed by a persistent three-tier memory layer and a goal chaining system for multi-step workflows.

**Version:** 0.3.0 &nbsp;|&nbsp; **Platform:** Windows 10/11 &nbsp;|&nbsp; **Python:** 3.11+ &nbsp;|&nbsp; **Model:** Gemini 2.5 Flash

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Core Pipeline](#core-pipeline)
- [Two-Pass Planning](#two-pass-planning)
- [Goal Chaining](#goal-chaining)
- [Memory Layer](#memory-layer)
- [Capability Layer](#capability-layer)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [Configuration Reference](#configuration-reference)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Logging Standards](#logging-standards)
- [Roadmap](#roadmap)
- [License](#license)

---

## Overview

ALARA is not a voice assistant, macro recorder, or conversational chatbot. It is an autonomous planning and execution engine for desktop tasks. A user provides a goal in natural language and ALARA decomposes it into a structured `TaskGraph` of typed, ordered, verifiable steps, executes each step against real system state, validates outcomes programmatically, and recovers from failures using LLM-guided reflection.

The system is designed around four principles:

**Verification-first execution.** Every step has a declared verification method. Execution is not considered successful until the verifier confirms real-world state matches the expected outcome. ALARA does not trust exit codes alone.

**Adaptive recovery.** When verification fails, the Reflector sends full execution context — original goal, complete plan, prior results, failure details — to Gemini and receives corrected actions or alternative paths. Recovery is not hardcoded; it is reasoned.

**Persistent memory.** ALARA learns from every execution. Path aliases, tool preferences, and successful task patterns are stored in a SQLite-backed memory layer and injected into every subsequent planning invocation, making the system progressively more accurate over time.

**Goal chaining.** Multiple goals can be chained in a single session. Each goal's outputs — paths created, files written — are passed as structured context to the next goal's planner, enabling multi-step workflows without repeating yourself.

---

## Architecture

### System Diagram

```text
         ┌─────────────────────────────────────────────┐
         │              CLI Entrypoint                  │
         │  main.py  ──  --goal / --then / --interactive│
         └────────────────────┬────────────────────────┘
                              │
         ┌────────────────────▼────────────────────────┐
         │              ChainContext                    │
         │   Accumulates results across chained goals   │
         └────────────────────┬────────────────────────┘
                              │
         ┌────────────────────▼────────────────────────┐
         │           Goal Understander                  │
         │            (GoalContext)                     │
         └────────────────────┬────────────────────────┘
                              │
         ┌────────────────────▼────────────────────────┐
         │         Two-Pass Planner                     │
         │  Pass 1: _build_approach() → structured JSON │
         │  Pass 2: step generation with approach ctx   │
         │          + memory context                    │
         │          + chain context (if chaining)       │
         └────────────────────┬────────────────────────┘
                              │
         ┌────────────────────▼────────────────────────┐
         │             Orchestrator                     │
         │   ┌─────────────────────┐                   │
         │   │  Execution Router   │                   │
         │   │  └► Filesystem      │                   │
         │   │  └► CLI             │                   │
         │   │  └► System          │                   │
         │   │  └► Code            │                   │
         │   └──────────┬──────────┘                   │
         │              ▼                               │
         │          Verifier                            │
         │       (real-world check)                     │
         │              │                               │
         │    ┌─────────▼──────────┐                   │
         │    │     Reflector      │                   │
         │    │  (on failure only) │                   │
         │    └────────────────────┘                   │
         └────────────────────┬────────────────────────┘
                              │
         ┌────────────────────▼────────────────────────┐
         │             Memory Layer                     │
         │  Session │ Preferences │ Skills              │
         │       SQLite + WAL mode                      │
         └─────────────────────────────────────────────┘
```

---

## Core Pipeline

### Goal Understander

`core/goal_understander.py`

Parses raw natural language input into a structured `GoalContext` using Gemini 2.5 Flash. Extracts normalized goal intent, operational scope (`filesystem`, `cli`, `mixed`, `system`), explicit constraints, inferred working directory, and estimated complexity (`simple`, `moderate`, `complex`). Implements a guaranteed `from_raw` fallback — the understander never raises, ensuring the pipeline always receives a valid context object.

### Two-Pass Planner

`core/planner.py`

See [Two-Pass Planning](#two-pass-planning) for full details.

### Code Context Builder

`core/code_context.py`

Provides project-aware context injection for the planning phase. Automatically detects Python projects, scans directory structures, and builds structured summaries of key files including main entry points, configuration files, and project structure. Enhances planning accuracy by providing relevant code context without requiring conversational state.

### TaskGraph Validation

`schemas/task_graph.py`

`TaskGraph` performs structural validation on construction:
1. Rejects empty step lists
2. Detects and renumbers duplicate step IDs, remapping all `depends_on` references
3. Validates all `depends_on` targets exist post-normalization
4. Runs DFS cycle detection, raising `ValueError` with the full cycle path if found

`next_pending_step()` returns the first `PENDING` step whose dependencies are all `DONE`. `SKIPPED`, `FAILED`, and `RUNNING` statuses do not satisfy dependency requirements.

### Orchestrator

`core/orchestrator.py`

Executes a `TaskGraph` through the full orchestration loop with a maximum of 3 retries per step:

```
get next pending step
        ↓
route to capability layer
        ↓
execute step → increment attempts
        ↓
verify real-world outcome
        ↓ (on failure)
retry if attempts < MAX_RETRIES
        ↓ (on max retries)
invoke Reflector → apply modified step / skip / escalate
```

Exposes `last_execution_log` property for chain context extraction after each goal completes.

### Execution Router

`core/execution_router.py`

Routes each `Step` to the correct capability based on `step_type` and `preferred_layer` in strict priority order: `FilesystemCapability` → `CLICapability` → `SystemCapability` → `CodeCapability` → app adapter fallback → UI automation fallback. Unimplemented layers log a `WARNING` and fall back to CLI where possible.

### Verifier

`core/verifier.py`

Validates real-world state after every step execution. Verification is not optional — every step declares a `verification_method` and the Verifier executes the appropriate check:

| Method | What is checked |
|---|---|
| `check_path_exists` | File or directory exists on disk |
| `check_file_contains` | File content includes expected text |
| `check_exit_code_zero` | Command returned exit code 0 |
| `check_process_running` | Named process is active in tasklist |
| `check_port_open` | TCP port accepts connections |
| `check_output_contains` | Command output includes expected content |
| `check_directory_not_empty` | Directory exists and has at least one entry |
| `none` | No verification required — always passes |

Unknown verification methods log a `WARNING` and pass rather than raising, preserving pipeline stability.

### Reflector

`core/reflector.py`

Invoked when a step exhausts its retry budget. Sends full execution context to Gemini 2.5 Flash at `temperature=0.3` and receives one of three actions:

- **retry** — Gemini provides a modified step with corrected operation, parameters, or approach. The Orchestrator applies the modification, resets `attempts` to 0, and retries.
- **skip** — Step is marked `SKIPPED` and execution continues with dependent steps unblocked where possible.
- **escalate** — Step is marked `FAILED`, the failure reason is recorded, and the Orchestrator terminates the task.

The Reflector never raises. On any API or parse failure it returns `action="escalate"` with the error message as the reason. Strips markdown code fences from Gemini responses before JSON parsing.

---

## Two-Pass Planning

For goals classified as `complex`, the planner runs in two passes before generating steps.

**Pass 1 — Approach (`_build_approach()`)**

A separate Gemini call produces a structured JSON approach document containing:

```json
{
  "phases": [...],
  "critical_paths": [...],
  "risks": [...],
  "estimated_steps": 12
}
```

This call uses `system_instruction` passed to the `GenerativeModel` constructor (not `generate_content`) and `max_output_tokens=4096` to prevent truncation on large plans.

If Pass 1 fails for any reason, a `WARNING` is logged and the planner falls back gracefully to single-pass planning. Pass 1 failure never aborts execution.

**Pass 2 — Step generation**

The approach JSON is injected into the user message alongside the memory context and (if chaining) the chain context. The planner produces the full `TaskGraph` with full awareness of the planned approach.

Simple and moderate goals skip Pass 1 entirely — no extra Gemini call, no latency cost.

**Planning rules enforced in both passes:**

- NEVER use `write_file` — use `create_file` (filesystem) instead
- NEVER generate `check_path_exists` guard steps — `create_directory` and `create_file` are idempotent
- NEVER generate server-start steps (uvicorn, npm start, etc.)
- NEVER generate curl/HTTP test steps
- Final step must be `create_file` or `run_command` (pip install/freeze)
- Full operation allowlist provided to prevent invented operations

---

## Goal Chaining

Goal chaining allows multiple goals to execute in sequence within a single session, with each goal's planner receiving structured context from all previously completed goals.

### How it works

After each goal completes, ALARA extracts key outputs from the execution log — verified paths, file creation results — and stores them in a `ChainContext`. When the next goal is planned, the chain context is injected into the planner prompt:

```
=== CHAIN CONTEXT ===
Previous goals completed in this session:

Goal 1: create a folder called chaintest on desktop
Status: success
Steps completed: 1/1
Key outputs:
  - C:\Users\Anubhav Gupta\Desktop\chaintest

=== END CHAIN CONTEXT ===
```

The planner is instructed to use paths from prior goals rather than reconstructing them, enabling precise multi-step workflows without re-specifying paths.

### Batch chaining with `--then`

```powershell
python -m alara.main `
  --goal "create a folder called myproject on desktop" `
  --then "create a file called main.py in myproject with a FastAPI hello world" `
  --then "create a requirements.txt in myproject with fastapi and uvicorn"
```

Goals execute in order. If a goal fails, the chain continues to the next goal rather than aborting.

### Interactive chaining with `--interactive`

```powershell
python -m alara.main --goal "create a folder called workspace on desktop" --interactive
# After goal completes, prompts: Chain another goal? (Enter to exit)
```

Type any follow-up goal and press Enter. The full chain context from all prior goals in the session is available to each chained goal. Press Enter on an empty line to exit.

`--then` and `--interactive` can be combined — batch goals run first, then the interactive prompt appears.

### Chain summary

When more than one goal completes in a session, a summary is displayed:

```
Chain complete: 3 goals completed: 3 success
```

---

## Memory Layer

`memory/`

A production-ready, thread-safe, SQLite-backed memory system with three tiers. All access is through the `MemoryManager` singleton. The database runs in WAL mode for concurrent read access. Schema versioning is implemented from day one with a migration hook for future schema evolution.

### Session Memory

`memory/session.py`

Tracks every goal execution within and across sessions. Each `SessionEntry` records the original goal, scope, final status (`success`, `partial`, `failed`), step counts, full execution log, and UTC timestamps. Queryable by recency, session ID, and goal text search.

### Preference Memory

`memory/preferences.py`

Persistent key-value store for user preferences, tool choices, and path aliases. Preferences carry confidence scores, usage counts, and provenance (`user_explicit`, `inferred`, `default`). Seeded with platform defaults on first run.

**Automatic inference:** After every successful execution, `infer_from_execution()` extracts path aliases from step parameters (mapping noun phrases in the goal to absolute paths used), tool preferences from CLI commands, and package patterns from `pip install` invocations. Inference is wrapped in `try/except` and never affects the execution flow.

**Path alias resolution** uses `_best_alias_path()` which walks path segments to find the segment best matching the noun phrase, returning the path up to that segment. File paths are always truncated to their parent directory — aliases always point to directories, never files.

A `RESERVED_PATH_SEGMENTS` blocklist prevents high-level Windows system directories (`users`, `appdata`, `windows`, `program files`, etc.) from ever being stored as aliases. A one-time startup migration (`_fix_stale_file_aliases`) cleans any pre-existing aliases that point to files or reserved segments.

**Path aliases** are the most impactful feature — once ALARA learns that "my projects folder" maps to `C:/Users/Anubhav Gupta/Desktop/Projects`, that mapping is injected into every subsequent planning invocation via the memory context summary.

### Skill Memory

`memory/skills.py`

Stores successful `TaskGraph` executions as reusable templates. Skills are retrieved using word-overlap similarity search with a composite ranking score:

```
score = (overlap × 0.6) + (success_rate × 0.3) + (recency × 0.1)
```

Where `success_rate = success_count / (success_count + failure_count + 1)` and `recency = 1.0` if used within 7 days, `0.5` within 30 days, `0.0` otherwise. Skills with similarity above 0.8 are deduplicated — repeated similar goals update the existing skill's statistics rather than creating a new entry.

### Memory Context Injection

Before every planning invocation, `MemoryManager.build_context()` assembles a `MemoryContext` containing recent goals, relevant skills, relevant preferences, and all known path aliases. This context is serialized as a structured summary string and appended to the Gemini planning prompt, giving the planner awareness of prior work without requiring conversational state.

### Database

`memory/database.py`

Thread-safe singleton `DatabaseManager` with per-call connections (not shared), WAL journal mode, foreign key enforcement, and retry logic on `OperationalError: database is locked` (3 attempts with 100ms backoff). Indexed on `sessions.created_at`, `sessions.session_id`, `skills.scope`, `preferences.category`, and `preferences.key` for sub-100ms `build_context()` performance.

---

## Capability Layer

All capabilities inherit from `BaseCapability` and implement a single entry point:

```python
class BaseCapability(ABC):
    @abstractmethod
    def execute(self, operation: str, params: dict) -> CapabilityResult:
        ...

    def supports(self, operation: str) -> bool:
        return False
```

All operations return `CapabilityResult` and never raise — exceptions are caught internally and returned as `CapabilityResult.fail(error=str(e))`.

### FilesystemCapability

`capabilities/filesystem.py`

Uses `pathlib.Path` exclusively. Supports: `create_directory`, `create_file`, `write_file`, `read_file`, `delete_file`, `delete_directory`, `move_file`, `copy_file`, `list_directory`, `search_files`, `check_path_exists`.

`create_file` is idempotent — it overwrites existing files when content is provided. `create_directory` uses `mkdir(parents=True, exist_ok=True)`.

Path resolution via `_resolve(path: str) -> Path` handles all Windows path variants in order:
1. Substitute `$env:USERPROFILE`, `%USERPROFILE%`, `$env:HOME`, `$HOME`
2. Expand `~` via `Path.expanduser()`
3. Anchor remaining relative paths to `Path.home()` — nothing resolves relative to the process working directory

### CLICapability

`capabilities/cli.py`

Executes shell commands via `subprocess.run(shell=True, capture_output=True, text=True)`. Captures stdout, stderr, and returncode. Working directory resolved via `_resolve_dir()` using the same path resolution logic as `FilesystemCapability`. Default timeout read from `STEP_TIMEOUT_S` environment variable (default 30s). Both stdout and stderr included in result metadata for Reflector context.

### SystemCapability

`capabilities/system.py`

Handles `get_env_var` (with Windows-specific fallback chain: `USERPROFILE` → `HOMEDRIVE+HOMEPATH` when `HOME` is requested), `set_env_var`, and `check_process` via `tasklist /FI`.

### CodeCapability

`capabilities/code.py`

Advanced code analysis and editing capability supporting Python AST parsing and multi-language file operations. Supports: `read_file`, `read_lines`, `analyze_structure`, `edit_file`, `append_to_file`, `insert_after_line`, `summarize_file`, `scan_project`, `check_contains`.

Features include:
- Python AST structure analysis with class, function, import extraction
- Multi-encoding support (UTF-8, Latin-1 fallback)
- Project scanning with configurable extensions and exclusion patterns
- Line-based editing with 1-indexed positioning
- File content search and verification

---

## Getting Started

### Prerequisites

- Python 3.11 or later
- Gemini API key from [Google AI Studio](https://aistudio.google.com)

### Installation

```powershell
git clone https://github.com/your-username/alara.git
cd alara
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

```powershell
copy .env.example .env
```

Edit `.env`:

```env
GEMINI_API_KEY=your_key_here
MAX_RETRIES=3
STEP_TIMEOUT_S=30
DEBUG=false
LOG_FILE=alara.log
DB_PATH=alara.db
```

---

## Usage

### Single goal

```powershell
python -m alara.main --goal "create a Python project called myapp"
```

### Goal chaining with `--then`

```powershell
python -m alara.main `
  --goal "create a folder called chaintest on desktop" `
  --then "create a file called hello.txt in chaintest with the text 'hello'"
```

### Interactive chaining with `--interactive`

```powershell
python -m alara.main --goal "create a folder called workspace on desktop" --interactive
# After goal completes:
# Chain another goal? (Enter to exit) _
```

### Debug mode

```powershell
python -m alara.main --goal "create a REST API with JWT auth" --debug
# Prints: GoalContext, Pass 1 Approach JSON (if complex), raw Gemini response,
#         execution log, chain context, memory health
```

### Example goals

| Goal | What ALARA does |
|---|---|
| `create a Python project called myapp with a venv` | Creates directory, initializes virtual environment, verifies both |
| `build a REST API with JWT authentication, SQLite database, and full CRUD endpoints for a users resource in documents` | Two-pass planning: 6-phase approach → 17-step TaskGraph covering scaffold, models, auth, routes, and pip freeze |
| `create a folder called output in the documents folder inside downloads` | Resolves nested path, creates both directories with dependency ordering |
| `install requests in the testapp virtual environment` | Locates venv Python executable, runs pip install, verifies exit code |
| `find all .tmp files in Downloads and delete them` | Searches for matches, deletes each, verifies deletion |
| `analyze the structure of main.py and show me the classes and functions` | Uses CodeCapability to parse Python AST, extracts classes, methods, functions, and imports with line counts |
| `edit the config.py file to replace DEBUG=True with DEBUG=False` | Reads file, performs targeted content replacement, verifies change was applied |
| `create a folder called myproject on desktop` → `create main.py in myproject with a FastAPI hello world` | Goal 2 planner receives chain context with `myproject` absolute path — resolves file location without re-specification |

---

## Configuration Reference

| Variable | Default | Required | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | — | Yes | Gemini 2.5 Flash API key for planning and reflection |
| `GEMINI_MODEL` | `gemini-2.5-flash` | No | Gemini model variant to use |
| `MAX_RETRIES` | `3` | No | Maximum retry attempts per step before Reflector invocation |
| `STEP_TIMEOUT_S` | `30` | No | Per-step CLI execution timeout in seconds |
| `DEBUG` | `false` | No | Enables verbose output including raw Gemini responses and Pass 1 approach JSON |
| `LOG_FILE` | `alara.log` | No | Path for persistent log output |
| `DB_PATH` | `alara.db` | No | SQLite memory database path |

---

## Project Structure

```text
alara/
├── .env.example
├── .gitignore
├── __init__.py
├── main.py                          # CLI entrypoint — --goal / --then / --interactive
├── README.md
├── requirements.txt
│
├── capabilities/
│   ├── base.py                      # BaseCapability, CapabilityResult
│   ├── cli.py                       # subprocess-based CLI execution
│   ├── code.py                      # Code analysis and editing (AST, line ops)
│   ├── filesystem.py                # pathlib-based filesystem operations
│   ├── system.py                    # env vars, process checking
│   └── windows/
│       ├── app_adapters.py          # Windows app automation (placeholder)
│       └── os_control.py            # Windows OS control (placeholder)
│
├── core/
│   ├── chain.py                     # ChainContext, ChainEntry — goal chaining
│   ├── code_context.py              # Project-aware context building
│   ├── execution_router.py          # Step-to-capability routing
│   ├── goal_understander.py         # Raw input → GoalContext
│   ├── orchestrator.py              # Full orchestration loop + last_execution_log
│   ├── planner.py                   # Two-pass GoalContext → TaskGraph
│   ├── reflector.py                 # Failure reflection and recovery
│   └── verifier.py                  # Post-step verification
│
├── memory/
│   ├── __init__.py                  # MemoryManager singleton
│   ├── database.py                  # DatabaseManager, migrations, WAL
│   ├── models.py                    # SessionEntry, PreferenceEntry, SkillEntry
│   ├── preferences.py               # Preferences, path aliases, inference
│   ├── session.py                   # Session tracking and history
│   └── skills.py                    # Skill storage and similarity search
│
├── schemas/
│   ├── goal.py                      # GoalContext
│   └── task_graph.py                # TaskGraph, Step, StepResult, enums
│
└── tests/
    ├── conftest.py
    ├── run_tests.py
    ├── test_execution_streamlined.py
    └── test_planner.py
```

---

## Testing

### Planner integration tests

```powershell
python -m tests.test_planner
```

Validates the planning stack against 8 benchmark goals with 14 assertions per goal covering step schema integrity, dependency graph correctness, enum validity, verification method whitelist compliance, path normalization, and timestamp format. Exits with code `1` if any assertion fails. Requires `GEMINI_API_KEY` in `.env`.

### Memory layer health check

```powershell
python -c "
from dotenv import load_dotenv
load_dotenv()
from alara.memory import MemoryManager
import json
print(json.dumps(MemoryManager.get_instance().health_check(), indent=2))
"
```

### Path alias inspection

```powershell
python -c "
from alara.memory import MemoryManager
memory = MemoryManager.get_instance()
aliases = memory.preferences.get_all_path_aliases()
for alias, path in aliases.items():
    print(f'  {alias} -> {path}')
"
```

### End-to-end execution

```powershell
python -m alara.main --debug --goal "create a folder called test on my desktop"
```

---

## Logging Standards

| Component | INFO | WARNING | ERROR |
|---|---|---|---|
| Orchestrator | Step start, step success, retry notice, skip notice | Step failure, verification failure, fallback used | Step escalated, unrecoverable failure |
| Router | — | Capability not implemented, fallback used | Routing exception |
| Verifier | — | Unknown verification method | — |
| Reflector | Reflection started, action decided | Parse failure, fallback to escalate | API failure |
| Capabilities | Operation, resolved path, command | Path not found, non-zero exit | Exception during execution |
| Memory | Initialization, successful stores, alias inference | Inference failures, stale alias cleanup | Database errors |
| Planner | Planning started, Pass 1 approach built, steps parsed | Pass 1 failure (fallback to single-pass), JSON retry | — |

---

## Roadmap

### Near Term
- **`google.genai` migration** — migrate from deprecated `google.generativeai` package to `google.genai`
- **Code context targeting** — detect and scan the target project rather than the Alara root when running from the Alara directory
- **`alara.db` growth management** — session log pruning and database compaction

### Medium Term
- **Multi-agent framework** — base `Agent` class with independent planning loops and model assignment per agent type (Coding Agent, Writing Agent, Research Agent)
- **Master Orchestrator upgrade** — goal decomposition into agent assignments rather than single-agent step sequences
- **Parallel agent execution** — independent agents running concurrently via async coordination
- **Voice input integration** — Deepgram streaming for microphone input
- **Playwright browser automation** — full Chrome/Edge CDP control
- **VS Code automation** — UI automation via keyboard shortcuts and CLI

### Long Term
- **Multi-device memory sync** — PostgreSQL-backed preference and skill synchronization across machines
- **macOS support** — platform-specific capability implementations
- **Linux support** — full Linux distribution compatibility
- **Plugin system** — third-party capability development framework
- **Enterprise features** — team collaboration, role-based access control, and audit logging

---

## License

MIT