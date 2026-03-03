"""
Pytest configuration and shared fixtures for ALARA tests.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

# Ensure `alara` package imports work
_THIS_FILE = Path(__file__).resolve()
_PACKAGE_ROOT = _THIS_FILE.parents[1]
_PROJECT_ROOT = _THIS_FILE.parents[2]
for _candidate in (_PROJECT_ROOT, _PACKAGE_ROOT):
    candidate_str = str(_candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)


@pytest.fixture(scope="session")
def test_goals() -> Dict[str, list]:
    """Shared test goals for different categories."""
    return {
        "planner": [
            "Create a new Python project called myapp with a virtual environment",
            "Find all PDF files on my desktop and move them to a folder called Documents/PDFs", 
            "Delete all .tmp and .log files in my Downloads folder",
            "Set up a FastAPI project with a Postgres database called myapp_db",
            "Create a folder structure for a new React project called dashboard",
            "Find the largest 10 files in my Documents folder and list them",
            "Rename all images in my Downloads folder to include today's date",
            "Install git if not already installed and configure my username as Anubhav",
        ],
        "execution": [
            "create a folder called test_execution on my desktop",
            "create a file called hello_execution.txt on my desktop with the text 'Test Content'",
        ],
        "integration": [
            "list the contents of my desktop",
            "check if notepad is running",
        ]
    }


@pytest.fixture(scope="session")
def allowed_verification_methods() -> set:
    """Allowed verification methods for task validation."""
    return {
        "check_path_exists",
        "check_exit_code_zero", 
        "check_process_running",
        "check_file_contains",
        "check_directory_not_empty",
        "check_port_open",
        "check_output_contains",
        "none",
    }


@pytest.fixture(scope="function")
def cleanup_desktop():
    """Cleanup function to remove test files/folders from desktop."""
    created_items = []
    
    def track_item(path: str):
        created_items.append(Path.home() / "Desktop" / path)
    
    yield track_item
    
    # Cleanup
    for item in created_items:
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                import shutil
                shutil.rmtree(item)
        except Exception:
            pass  # Ignore cleanup errors


@pytest.fixture(scope="session")
def alara_components():
    """Shared ALARA components for testing."""
    from dotenv import load_dotenv
    load_dotenv()
    
    from alara.core.goal_understander import GoalUnderstander
    from alara.core.planner import Planner
    from alara.core.orchestrator import Orchestrator
    from alara.capabilities.filesystem import FilesystemCapability
    from alara.capabilities.cli import CLICapability
    from alara.capabilities.system import SystemCapability
    
    return {
        "understander": GoalUnderstander(),
        "planner": Planner(),
        "orchestrator": Orchestrator(),
        "filesystem": FilesystemCapability(),
        "cli": CLICapability(),
        "system": SystemCapability(),
    }
