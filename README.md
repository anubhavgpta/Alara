<p align="center">
  <img src="./alara-banner.jpg" alt="ALARA Banner" width="100%" />
</p>

# ALARA
**Ambient Language & Reasoning Assistant**

ALARA is an agentic desktop AI platform for Windows that transforms natural language goals into executable tasks with comprehensive verification and adaptive error recovery.

Version: 0.2.0  |  Platform: Windows 10/11  |  Python: 3.11+

## Overview

ALARA is an autonomous planning and execution engine for desktop tasks. It is not a voice assistant, macro recorder, or conversational chatbot. A user provides a goal in natural language, and ALARA decomposes it into a structured execution plan with typed steps, dependencies, verification methods, and fallback strategies, then executes the plan with real-world verification and adaptive error recovery.

Current build: Complete execution engine with planning, routing, verification, and reflection capabilities fully operational.

## Architecture

ALARA implements a comprehensive orchestration loop consisting of five core components:

### Core Components

**Goal Understander:** Parses raw input into a structured `GoalContext` that captures normalized intent, operational scope, explicit constraints, inferred working directory, and estimated complexity.

**Planner:** Sends `GoalContext` to Gemini 2.5 Flash using a constrained planning prompt and receives a typed `TaskGraph` of ordered atomic steps. Each step includes operation, parameters, expected outcome, verification method, dependencies, and fallback strategy.

**Execution Router:** Selects the best execution layer for each step in strict priority order: native OS API, application adapter, CLI execution, then UI automation as a last resort.

**Verifier:** Validates real-world state after each step against expected outcomes using programmatic checks such as file existence, process state, exit code status, port availability, and output inspection.

**Reflector:** On failed verification, sends full execution context to Gemini, including original goal, full plan, prior step results, and failure details. Gemini returns corrected actions or alternative paths, and ALARA retries within configured limits.

### Execution Flow

```text
User Input
    │
    ▼
Goal Understander ──► extracts scope, constraints, working directory
    │
    ▼
Planner ──────────► decomposes goal into typed, ordered TaskGraph
    │
    ▼
┌─────────────────────────────────────────┐
│           Orchestration Loop            │
│                                         │
│   Execution Router                      │
│   └─► Filesystem → CLI → System →      │
│        App Adapter → UI Automation      │
│              │                          │
│   Verifier ◄─┘                          │
│   └─► confirmed / failed                │
│              │                          │
│   Reflector (on failure)                │
│   └─► replan → retry → skip → escalate  │
└─────────────────────────────────────────┘
    │
    ▼
Result
```

## Capabilities

### Filesystem Operations
- **Directory Management:** Create, delete, move, and list directories with parent directory auto-creation
- **File Operations:** Create, read, write, copy, move, and delete files with content verification
- **Path Resolution:** Support for Windows environment variables (`$env:USERPROFILE`, `$HOME`) and user home expansion (`~`)
- **Search & Discovery:** Recursive file pattern matching and absolute path enumeration
- **Verification:** Real-world state checking including path existence, content validation, and directory non-emptiness

### Command Line Interface
- **Command Execution:** Run shell commands with configurable timeouts and working directories
- **Output Capture:** Comprehensive stdout/stderr capture with return code tracking
- **Environment Control:** Working directory resolution and validation before execution
- **Error Handling:** Graceful timeout handling and exception capture with detailed metadata

### System Integration
- **Environment Variables:** Read and set system and user environment variables with Windows-specific handling
- **Process Management:** Check running processes via Windows tasklist with psutil fallback
- **System Queries:** Retrieve system information and validate system state

### Verification & Validation
- **Path Verification:** File and directory existence checking with resolved path validation
- **Content Verification:** File content inspection for expected text and patterns
- **Process Verification:** Running process validation with fresh checking capability
- **Network Verification:** Port availability checking with host connectivity validation
- **Output Verification:** Command output inspection for expected content and patterns
- **Exit Code Verification:** Process exit code validation for success/failure determination

### Adaptive Error Recovery
- **Intelligent Reflection:** LLM-powered failure analysis with context-aware alternative generation
- **Retry Logic:** Configurable retry attempts with modified step parameters and approaches
- **Fallback Strategies:** Optional step skipping and escalation to human intervention
- **Context Preservation:** Full execution context maintenance for reflection decisions

## Implementation Details

### Capability Layer Architecture

All capabilities inherit from a standardized `BaseCapability` interface:

```python
class BaseCapability(ABC):
    @abstractmethod
    def execute(self, operation: str, params: dict) -> CapabilityResult:
        """Execute one operation with operation-specific params."""
    
    def supports(self, operation: str) -> bool:
        """Return whether this capability handles the operation."""
        return False
```

### Result Standardization

All operations return structured `CapabilityResult` objects:

```python
@dataclass
class CapabilityResult:
    success: bool
    output: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Path Resolution

Comprehensive Windows path handling with support for:
- User home expansion (`~`)
- Environment variable substitution (`$HOME`, `$env:USERPROFILE`)
- Absolute and relative path resolution
- Cross-platform compatibility using `pathlib.Path`

### Verification Methods

The verifier supports multiple verification strategies:
- `check_path_exists`: Validates file/directory existence
- `check_file_contains`: Inspects file content for expected text
- `check_exit_code_zero`: Validates successful command execution
- `check_process_running`: Confirms process availability
- `check_port_open`: Validates network port accessibility
- `check_output_contains`: Inspects command output
- `check_directory_not_empty`: Validates directory contents
- `none`: Bypasses verification for non-critical steps

### Reflection & Recovery

The reflector implements sophisticated error recovery:
- **Context Analysis**: Full execution context including goal, plan, and failure details
- **Alternative Generation**: LLM-powered generation of modified approaches
- **Action Decision**: Intelligent selection between retry, skip, or escalate actions
- **Step Modification**: Dynamic parameter and approach adjustment for retries

## Getting Started

### Prerequisites

ALARA requires Python 3.11 or later. An NVIDIA GPU is optional and not required for this release. Gemini API access is required before setup.

**Gemini API Key**

ALARA uses Gemini 2.5 Flash for planning and reflection. Create a free API key at `https://aistudio.google.com`.

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

```env
GEMINI_API_KEY=your_key_here
MAX_RETRIES=3
STEP_TIMEOUT_S=30
DEBUG=false
LOG_FILE=alara.log
DB_PATH=alara.db
```

## Usage

### Interactive Mode

```powershell
# If your current directory is the parent repo directory:
python -m alara.main

# If your current directory is the package directory:
python main.py
```

ALARA starts a prompt loop. Enter a natural language goal and press Enter. ALARA runs the complete planning and execution pipeline with real-time progress feedback.

### Single Goal Mode

```powershell
python -m alara.main --goal "create a Python project called myapp"
```

This mode plans and executes one goal non-interactively with auto-confirmation.

### Debug Mode

```powershell
python -m alara.main --debug
```

Debug mode prints parsed `GoalContext`, raw Gemini planner response, execution logs, and detailed verification results.

### Example Goals

| Goal | What ALARA Does |
|---|---|
| "Create a FastAPI project called myapp with a venv" | Scaffolds the project directory, creates a virtual environment, installs FastAPI, and generates `main.py` with a hello-world route. |
| "Find all .log files in Downloads and delete them" | Searches for matching files, deletes each match, and verifies deletion. |
| "Set up a git repository in my current project folder" | Runs `git init`, creates a Python `.gitignore`, and makes an initial commit. |
| "Rename all images in Desktop/photos to include today's date" | Enumerates image files, generates date-prefixed names, renames files, and verifies results. |
| "Find the 10 largest files in Documents" | Scans recursively, sorts by file size, and prints a formatted top-10 report. |
| "Install Python dependencies from requirements.txt" | Detects active virtual environment, runs `pip install -r requirements.txt`, and validates installed packages. |
| "Create a folder called test on my desktop" | Creates the specified directory with path resolution and existence verification. |
| "Create a file called hello.txt on my desktop with the text 'Hello World'" | Creates the file with specified content and verifies file creation and content. |

## Testing

### Planner Validation Tests

Run planner integration checks over 8 benchmark goals:

```powershell
# From parent repo directory:
python -m tests.test_planner

# From package directory:
python -m tests.test_planner
```

Notes:
- `GEMINI_API_KEY` must be set in `.env`.
- The script exits with code `1` if any goal fails validation.
- It validates step schema integrity, dependencies, verification methods, path normalization, and timestamp format.

### End-to-End Execution Tests

The execution engine has been validated with comprehensive test scenarios:

```powershell
# Test filesystem operations
python -m alara.main --goal "create a folder called test on my desktop"

# Test file creation with content
python -m alara.main --goal "create a file called hello.txt on my desktop with the text 'Hello World'"

# Test directory listing
python -m alara.main --debug --goal "list the contents of my desktop"
```

## Project Structure

```text
alara/
├── .env.example                  # Environment variable template
├── .gitignore                    # Git ignore rules
├── __init__.py                   # Package marker
├── alara-banner.jpg              # README banner image
├── main.py                       # CLI entrypoint and orchestration loop
├── README.md                     # Product documentation
├── requirements.txt              # Python dependencies
├── test_results.json             # Test output artifact
├── capabilities/
│   ├── __init__.py               # Capabilities package marker
│   ├── base.py                   # Capability base contract and result types
│   ├── cli.py                    # CLI execution capability with subprocess handling
│   ├── filesystem.py             # Filesystem execution capability with pathlib
│   ├── system.py                 # System operations capability
│   └── windows/
│       ├── __init__.py           # Windows capabilities marker
│       ├── app_adapters.py       # App adapter capability
│       ├── os_control.py         # Native Windows control capability
│       └── ui_automation.py      # UI automation fallback capability
├── core/
│   ├── __init__.py               # Core package marker
│   ├── execution_router.py       # Step-to-capability routing logic
│   ├── goal_understander.py      # Raw goal to GoalContext extraction
│   ├── orchestrator.py           # Complete orchestration loop implementation
│   ├── planner.py                # GoalContext to TaskGraph planning
│   ├── reflector.py              # Failure reflection and adaptive recovery
│   └── verifier.py               # Step outcome verification with multiple methods
├── schemas/
│   ├── __init__.py               # Schemas package marker
│   ├── goal.py                   # GoalContext schema
│   └── task_graph.py             # TaskGraph and step schemas with validation
├── tests/
│   ├── __init__.py               # Test package marker
│   ├── test_planner.py           # Planner integration validation script
│   └── test_week56_integrations.py # Integration behavior tests
└── utils/
    ├── __init__.py               # Utilities package marker
    └── platform.py               # Platform/path helpers
```

## Configuration Reference

| Variable | Default | Required | Description |
|---|---|---|---|
| GEMINI_API_KEY | — | Yes | Gemini 2.5 Flash API key for planning and reflection. |
| MAX_RETRIES | 3 | No | Maximum retry attempts per step before escalation. |
| STEP_TIMEOUT_S | 30 | No | Timeout in seconds per step execution. |
| DEBUG | false | No | Enables verbose logging output and execution details. |
| LOG_FILE | alara.log | No | Log file path for persistent logging. |
| DB_PATH | alara.db | No | SQLite memory database path. |

## Logging Standards

ALARA implements comprehensive logging across all components:

- **Orchestrator:** INFO for step lifecycle events, WARNING for failures, ERROR for unrecoverable errors
- **Router:** WARNING for capability fallbacks, ERROR for routing exceptions
- **Verifier:** DEBUG for verification details, WARNING for unknown methods
- **Reflector:** INFO for reflection decisions, WARNING for parse failures, ERROR for API failures
- **Capabilities:** DEBUG for operation details, WARNING for expected failures, ERROR for exceptions

## Overlay UI

ALARA includes an Electron-based floating overlay triggered system-wide with `Ctrl+Space`. The overlay behaves as a command palette for submitting goals and observing execution state in real time, and communicates with the backend over local WebSocket `ws://localhost:8765`.

| State | Indicator Color | Meaning |
|---|---|---|
| Ready | White | Waiting for input. |
| Planning | Purple | Decomposing goal into executable steps. |
| Executing | Blue | Running the active step. |
| Verifying | Amber | Validating step outcome. |
| Reflecting | Red | Correcting a failed step via replan. |
| Done | Green | Task completed successfully. |
| Failed | Red | Task failed after maximum retries. |

```powershell
cd ui
npm install
npm start
```

## License

MIT
