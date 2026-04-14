# Alara

Ambient Language and Reasoning Assistant — a secure personal desktop AI assistant with a CLI/REPL interface powered by Gemini.

## Installation

```bash
pip install -e .
```

Requires Python 3.11+.

## First run

```bash
alara
```

On first launch, Alara runs an interactive setup wizard that:

- Collects your name, timezone, and response style preference
- Prompts for your Gemini API key (stored securely in the system keyring, never written to disk)
- Configures a sandboxed workspace directory

## Usage

Once setup is complete, type any request at the prompt:

```
Anubhav> What is the difference between TCP and UDP?
Anubhav> list my files
Anubhav> write a short cover letter for a software engineer role
Anubhav> exit
```

## Security model

- **Secrets**: API keys are stored in the OS keyring via `keyring`. They are never written to config files, logs, or environment variables.
- **File sandboxing**: All file reads and writes are restricted to the configured workspace directory. Paths outside the workspace are rejected.
- **Permission gates**: Write, delete, and network-send operations require explicit user confirmation before proceeding.

## Configuration

`config/alara.toml` is written by the wizard and contains only non-sensitive settings (name, timezone, workspace path, response style). It does not contain secrets.

## Architecture

```
alara/
  core/        — Gemini client, intent classification, dispatch router
  capabilities/ — research, file I/O, writing
  mcp/          — MCP client stub (L1 implementation pending)
  security/     — vault (keyring), permission gates, path sandbox
  setup/        — first-run wizard
  db.py         — SQLite session and message persistence
  main.py       — REPL entry point
```

## Dependencies

- `google-genai` — Gemini API SDK
- `prompt_toolkit` — REPL with history and masked input
- `keyring` — OS keyring integration
- `rich` — terminal formatting
- `httpx` — HTTP client (for future MCP transports)
- `mcp` — MCP protocol library (L1)
