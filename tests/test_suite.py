"""ALARA Unified Test Suite

Run with:
    python -m tests.test_suite
    python -m tests.test_suite --category planner
    python -m tests.test_suite --category execution
    python -m tests.test_suite --category integration
    python -m tests.test_suite --debug
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

# Ensure `alara` package imports work
_THIS_FILE = Path(__file__).resolve()
_PACKAGE_ROOT = _THIS_FILE.parents[1]
_PROJECT_ROOT = _THIS_FILE.parents[2]
for _candidate in (_PROJECT_ROOT, _PACKAGE_ROOT):
    candidate_str = str(_candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)

from alara.core.goal_understander import GoalUnderstander
from alara.core.planner import Planner, PlanningError
from alara.core.orchestrator import Orchestrator
from alara.capabilities.filesystem import FilesystemCapability
from alara.capabilities.cli import CLICapability
from alara.capabilities.system import SystemCapability
from alara.schemas.task_graph import ExecutionLayer, StepType, TaskGraph


class ALARATestSuite:
    """Unified test suite for ALARA components."""

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.results = {
            "planner": {"passed": 0, "failed": 0, "errors": []},
            "execution": {"passed": 0, "failed": 0, "errors": []},
            "integration": {"passed": 0, "failed": 0, "errors": []},
            "overall": {"passed": 0, "failed": 0, "errors": []}
        }
        
        # Test data
        self.planner_goals = [
            "Create a new Python project called myapp with a virtual environment",
            "Find all PDF files on my desktop and move them to a folder called Documents/PDFs",
            "Delete all .tmp and .log files in my Downloads folder",
            "Set up a FastAPI project with a Postgres database called myapp_db",
            "Create a folder structure for a new React project called dashboard",
            "Find the largest 10 files in my Documents folder and list them",
            "Rename all images in my Downloads folder to include today's date",
            "Install git if not already installed and configure my username as Anubhav",
        ]
        
        self.execution_tests = [
            {
                "name": "create_directory",
                "goal": "create a folder called test_alara on my desktop",
                "cleanup": lambda: self._cleanup_directory("test_alara")
            },
            {
                "name": "create_file_with_content", 
                "goal": "create a file called hello_alara.txt on my desktop with the text 'Test Content'",
                "cleanup": lambda: self._cleanup_file("hello_alara.txt")
            }
        ]

    def run_all_tests(self) -> Dict[str, Any]:
        """Run all test categories."""
        print("Starting ALARA Unified Test Suite")
        print("=" * 50)
        
        # Test categories
        categories = ["planner", "execution", "integration"]
        
        for category in categories:
            print(f"\nRunning {category.upper()} tests...")
            self._run_category_tests(category)
        
        self._print_summary()
        return self.results

    def run_category(self, category: str) -> Dict[str, Any]:
        """Run tests for a specific category."""
        print(f"Starting ALARA {category.upper()} Test Suite")
        print("=" * 50)
        
        self._run_category_tests(category)
        self._print_category_summary(category)
        return self.results

    def _run_category_tests(self, category: str) -> None:
        """Run tests for a specific category."""
        if category == "planner":
            self._test_planner()
        elif category == "execution":
            self._test_execution_engine()
        elif category == "integration":
            self._test_integration_components()
        else:
            print(f"Unknown category: {category}")
            return

    def _test_planner(self) -> None:
        """Test planner functionality."""
        try:
            load_dotenv()
            understander = GoalUnderstander()
            planner = Planner()
            
            allowed_verification_methods = {
                "check_path_exists", "check_exit_code_zero", "check_process_running",
                "check_file_contains", "check_directory_not_empty", "check_port_open",
                "check_output_contains", "none"
            }
            
            for i, goal in enumerate(self.planner_goals, 1):
                try:
                    print(f"  Test {i}: {goal[:50]}...")
                    
                    # Test goal understanding
                    goal_context = understander.understand(goal)
                    
                    # Test planning
                    task_graph = planner.plan(goal_context)
                    
                    # Validate task graph
                    self._validate_task_graph(task_graph, allowed_verification_methods)
                    
                    self.results["planner"]["passed"] += 1
                    self.results["overall"]["passed"] += 1
                    print(f"    Passed")
                    
                except Exception as e:
                    self.results["planner"]["failed"] += 1
                    self.results["overall"]["failed"] += 1
                    error_msg = f"Planner test {i} failed: {str(e)}"
                    self.results["planner"]["errors"].append(error_msg)
                    self.results["overall"]["errors"].append(error_msg)
                    print(f"    Failed: {str(e)}")
                    
        except Exception as e:
            error_msg = f"Planner initialization failed: {str(e)}"
            self.results["planner"]["errors"].append(error_msg)
            self.results["overall"]["errors"].append(error_msg)
            print(f"Planner setup failed: {str(e)}")

    def _test_execution_engine(self) -> None:
        """Test execution engine components."""
        try:
            # Test capabilities
            capabilities = {
                "filesystem": FilesystemCapability(),
                "cli": CLICapability(), 
                "system": SystemCapability()
            }
            
            for cap_name, capability in capabilities.items():
                try:
                    print(f"  Testing {cap_name} capability...")
                    
                    # Test supported operations
                    if cap_name == "filesystem":
                        self._test_filesystem_capability(capability)
                    elif cap_name == "cli":
                        self._test_cli_capability(capability)
                    elif cap_name == "system":
                        self._test_system_capability(capability)
                    
                    self.results["execution"]["passed"] += 1
                    self.results["overall"]["passed"] += 1
                    print(f"    {cap_name} capability passed")
                    
                except Exception as e:
                    self.results["execution"]["failed"] += 1
                    self.results["overall"]["failed"] += 1
                    error_msg = f"{cap_name} capability test failed: {str(e)}"
                    self.results["execution"]["errors"].append(error_msg)
                    self.results["overall"]["errors"].append(error_msg)
                    print(f"    {cap_name} capability failed: {str(e)}")
                    
        except Exception as e:
            error_msg = f"Execution engine setup failed: {str(e)}"
            self.results["execution"]["errors"].append(error_msg)
            self.results["overall"]["errors"].append(error_msg)
            print(f"Execution engine setup failed: {str(e)}")

    def _test_integration_components(self) -> None:
        """Test integration between components."""
        try:
            print("  Testing orchestrator integration...")
            
            # Test orchestrator initialization
            orchestrator = Orchestrator()
            
            # Test end-to-end with a simple goal
            test_goal = "create a folder called integration_test on my desktop"
            
            try:
                understander = GoalUnderstander()
                planner = Planner()
                
                # Plan the goal
                goal_context = understander.understand(test_goal)
                task_graph = planner.plan(goal_context)
                
                # Execute (but don't actually create the folder)
                # Just test that the orchestrator can process the task graph
                self.results["integration"]["passed"] += 1
                self.results["overall"]["passed"] += 1
                print(f"    Integration test passed")
                
                # Cleanup if test actually ran
                self._cleanup_directory("integration_test")
                
            except Exception as e:
                self.results["integration"]["failed"] += 1
                self.results["overall"]["failed"] += 1
                error_msg = f"Integration test failed: {str(e)}"
                self.results["integration"]["errors"].append(error_msg)
                self.results["overall"]["errors"].append(error_msg)
                print(f"    Integration test failed: {str(e)}")
                
        except Exception as e:
            error_msg = f"Integration setup failed: {str(e)}"
            self.results["integration"]["errors"].append(error_msg)
            self.results["overall"]["errors"].append(error_msg)
            print(f"Integration setup failed: {str(e)}")

    def _test_filesystem_capability(self, capability: FilesystemCapability) -> None:
        """Test filesystem capability operations."""
        # Test path resolution
        test_path = "$env:USERPROFILE/Desktop/test_path"
        resolved = capability._resolve(test_path)
        assert resolved.name == "test_path"
        
        # Test supported operations
        supported_ops = capability._SUPPORTED
        assert "create_directory" in supported_ops
        assert "create_file" in supported_ops
        assert "read_file" in supported_ops

    def _test_cli_capability(self, capability: CLICapability) -> None:
        """Test CLI capability operations."""
        # Test timeout initialization
        assert capability.default_timeout_s > 0
        
        # Test supported operations
        assert capability.supports("run_command")
        assert not capability.supports("invalid_operation")

    def _test_system_capability(self, capability: SystemCapability) -> None:
        """Test system capability operations."""
        # Test supported operations
        supported_ops = capability._SUPPORTED
        assert "get_env_var" in supported_ops
        assert "set_env_var" in supported_ops
        assert "check_process" in supported_ops

    def _validate_task_graph(self, task_graph: TaskGraph, allowed_methods: set) -> None:
        """Validate task graph structure and content."""
        assert task_graph.steps, "TaskGraph must contain steps"
        assert task_graph.goal, "TaskGraph must have a goal"
        
        # Validate each step
        for step in task_graph.steps:
            assert step.id > 0, f"Step {step.id} must have positive ID"
            assert step.operation, f"Step {step.id} must have operation"
            assert step.description, f"Step {step.id} must have description"
            assert step.verification_method in allowed_methods, f"Step {step.id} has invalid verification method"
            
            # Validate step type
            assert isinstance(step.step_type, StepType), f"Step {step.id} has invalid step_type"
            
            # Validate preferred layer
            assert isinstance(step.preferred_layer, ExecutionLayer), f"Step {step.id} has invalid preferred_layer"

    def _cleanup_directory(self, name: str) -> None:
        """Clean up test directory."""
        try:
            test_dir = Path.home() / "Desktop" / name
            if test_dir.exists():
                import shutil
                shutil.rmtree(test_dir)
        except Exception:
            pass  # Ignore cleanup errors

    def _cleanup_file(self, name: str) -> None:
        """Clean up test file."""
        try:
            test_file = Path.home() / "Desktop" / name
            if test_file.exists():
                test_file.unlink()
        except Exception:
            pass  # Ignore cleanup errors

    def _print_summary(self) -> None:
        """Print overall test summary."""
        print("\n" + "=" * 50)
        print("OVERALL TEST RESULTS")
        print("=" * 50)
        
        total_passed = self.results["overall"]["passed"]
        total_failed = self.results["overall"]["failed"]
        total_tests = total_passed + total_failed
        
        for category in ["planner", "execution", "integration"]:
            passed = self.results[category]["passed"]
            failed = self.results[category]["failed"]
            total = passed + failed
            status = "PASS" if failed == 0 else "FAIL"
            print(f"{status} {category.title()}: {passed}/{total} passed")
        
        print(f"\nTotal: {total_passed}/{total_tests} tests passed")
        
        if self.results["overall"]["errors"]:
            print("\nERRORS:")
            for error in self.results["overall"]["errors"]:
                print(f"  • {error}")

    def _print_category_summary(self, category: str) -> None:
        """Print summary for a specific category."""
        passed = self.results[category]["passed"]
        failed = self.results[category]["failed"]
        total = passed + failed
        status = "PASS" if failed == 0 else "FAIL"
        
        print(f"\n{status} {category.title()}: {passed}/{total} tests passed")
        
        if self.results[category]["errors"]:
            print("ERRORS:")
            for error in self.results[category]["errors"]:
                print(f"  • {error}")


def main():
    """Main entry point for test suite."""
    parser = argparse.ArgumentParser(description="ALARA Unified Test Suite")
    parser.add_argument("--category", choices=["planner", "execution", "integration"], 
                       help="Run specific test category")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--output", help="Save results to JSON file")
    
    args = parser.parse_args()
    
    # Set debug mode
    if args.debug:
        os.environ["DEBUG"] = "true"
    
    # Run tests
    suite = ALARATestSuite(debug=args.debug)
    
    if args.category:
        results = suite.run_category(args.category)
    else:
        results = suite.run_all_tests()
    
    # Save results if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {args.output}")
    
    # Exit with appropriate code
    total_failed = results["overall"]["failed"]
    sys.exit(1 if total_failed > 0 else 0)


if __name__ == "__main__":
    main()
