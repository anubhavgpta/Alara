"""
tests/test_intent.py

Intent classification benchmark for ALARA.
Run with: python -m tests.test_intent
"""

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.intent_engine import Action, IntentEngine


@dataclass
class TestCase:
    command: str
    expected_action: str
    expected_params: Dict[str, str]
    category: str


TEST_CASES = [
    # App Control (10)
    TestCase("open VS Code", "open_app", {"app_name": "vscode"}, "app_control"),
    TestCase("launch Chrome", "open_app", {"app_name": "google chrome"}, "app_control"),
    TestCase("open terminal", "open_app", {"app_name": "windows terminal"}, "app_control"),
    TestCase("close Chrome", "close_app", {"app_name": "google chrome"}, "app_control"),
    TestCase("shutdown VS Code", "close_app", {"app_name": "vscode"}, "app_control"),
    TestCase("switch to Firefox", "switch_app", {"app_name": "firefox"}, "app_control"),
    TestCase("open Notepad", "open_app", {"app_name": "notepad"}, "app_control"),
    TestCase("close terminal", "close_app", {"app_name": "windows terminal"}, "app_control"),
    TestCase("launch Slack", "open_app", {"app_name": "slack"}, "app_control"),
    TestCase("switch to VS Code", "switch_app", {"app_name": "vscode"}, "app_control"),
    # Terminal Commands (8)
    TestCase("run git status", "run_command", {"command": "git status"}, "terminal"),
    TestCase("git pull origin main", "run_command", {"command": "git pull origin main"}, "terminal"),
    TestCase("npm install", "run_command", {"command": "npm install"}, "terminal"),
    TestCase("python main.py", "run_command", {"command": "python main.py"}, "terminal"),
    TestCase("run pytest", "run_command", {"command": "pytest"}, "terminal"),
    TestCase("docker-compose up", "run_command", {"command": "docker-compose up"}, "terminal"),
    TestCase("clear terminal", "run_command", {"command": "clear"}, "terminal"),
    TestCase("pip install requests", "run_command", {"command": "pip install requests"}, "terminal"),
    # File Operations (7)
    TestCase("open main.py", "open_file", {"path": "main.py"}, "file_operations"),
    TestCase("open my downloads folder", "open_folder", {"path": "downloads"}, "file_operations"),
    TestCase("search for python files", "search_files", {"query": "*.py"}, "file_operations"),
    TestCase("open the config file", "open_file", {"path": "config"}, "file_operations"),
    TestCase("open desktop folder", "open_folder", {"path": "desktop"}, "file_operations"),
    TestCase("search for README files", "search_files", {"query": "README*"}, "file_operations"),
    TestCase("open requirements.txt", "open_file", {"path": "requirements.txt"}, "file_operations"),
    # Browser Operations (8)
    TestCase("open GitHub", "browser_navigate", {"url": "https://github.com"}, "browser"),
    TestCase("search for Python tutorials", "browser_search", {"query": "Python tutorials"}, "browser"),
    TestCase("navigate to stackoverflow.com", "browser_navigate", {"url": "https://stackoverflow.com"}, "browser"),
    TestCase("open a new tab", "browser_new_tab", {}, "browser"),
    TestCase("search for docker documentation", "browser_search", {"query": "docker documentation"}, "browser"),
    TestCase("go to google.com", "browser_navigate", {"url": "https://google.com"}, "browser"),
    TestCase("close this tab", "browser_close_tab", {}, "browser"),
    TestCase("search for react hooks", "browser_search", {"query": "react hooks"}, "browser"),
    # VS Code Operations (5)
    TestCase("open the app.py file in VS Code", "vscode_open_file", {"query": "app.py"}, "vscode"),
    TestCase("search for function definitions", "vscode_search", {"query": "function definitions"}, "vscode"),
    TestCase("open a new terminal in VS Code", "vscode_new_terminal", {}, "vscode"),
    TestCase("find the main function", "vscode_search", {"query": "main function"}, "vscode"),
    TestCase("open utils.py in VS Code", "vscode_open_file", {"query": "utils.py"}, "vscode"),
    # Window Management (4)
    TestCase("minimize window", "minimize_window", {}, "window_management"),
    TestCase("maximize this window", "maximize_window", {}, "window_management"),
    TestCase("take a screenshot", "take_screenshot", {}, "window_management"),
    TestCase("close this window", "close_window", {}, "window_management"),
    # System Operations (4)
    TestCase("turn up the volume", "volume_up", {"amount": 10}, "system"),
    TestCase("volume down", "volume_down", {"amount": 10}, "system"),
    TestCase("mute the volume", "volume_mute", {}, "system"),
    TestCase("lock my screen", "lock_screen", {}, "system"),
    # Unknown (4)
    TestCase("what's the weather like", "unknown", {"reason": "weather queries not supported"}, "unknown"),
    TestCase("tell me a joke", "unknown", {"reason": "joke requests not supported"}, "unknown"),
    TestCase("send an email", "unknown", {"reason": "email operations not supported"}, "unknown"),
    TestCase("play some music", "unknown", {"reason": "music playback not supported"}, "unknown"),
]


class IntentTestSuite:
    def __init__(self):
        self.engine = IntentEngine()
        self.results = []

    def run_test_case(self, test_case: TestCase) -> Tuple[bool, Action]:
        try:
            actual = self.engine.parse(test_case.command)
            action_match = actual.action == test_case.expected_action

            if test_case.expected_action == "unknown":
                passed = actual.action == "unknown"
            else:
                passed = action_match
                if passed and test_case.expected_params:
                    for key, expected_value in test_case.expected_params.items():
                        actual_value = actual.params.get(key, "")
                        if str(expected_value).lower() not in str(actual_value).lower():
                            passed = False
                            break
            return passed, actual
        except Exception as e:
            print(f"Error testing '{test_case.command}': {e}")
            return False, Action(action="error", params={"error": str(e)}, confidence=0.0, raw_text=test_case.command)

    def run_all_tests(self):
        print("Running intent classification test suite...")
        print(f"Testing {len(TEST_CASES)} commands\n")

        passed = 0
        failed = 0
        category_results = defaultdict(lambda: {"passed": 0, "total": 0})

        for i, test_case in enumerate(TEST_CASES, 1):
            print(f"[{i:2d}/50] Testing: '{test_case.command}'")
            test_passed, actual_action = self.run_test_case(test_case)
            category_results[test_case.category]["total"] += 1

            if test_passed:
                passed += 1
                category_results[test_case.category]["passed"] += 1
                print(f"  PASS: {actual_action.action} (confidence: {actual_action.confidence:.2f})")
            else:
                failed += 1
                print(f"  FAIL: Expected {test_case.expected_action}, got {actual_action.action}")
                print(f"        Expected params: {test_case.expected_params}")
                print(f"        Actual params: {actual_action.params}")
                print(f"        Confidence: {actual_action.confidence:.2f}")

            self.results.append(
                {
                    "command": test_case.command,
                    "expected": test_case.expected_action,
                    "actual": actual_action.action,
                    "passed": test_passed,
                    "confidence": actual_action.confidence,
                    "category": test_case.category,
                }
            )

        accuracy = (passed / len(TEST_CASES)) * 100
        print(f"\n{'=' * 60}")
        print(f"RESULTS: {passed}/{len(TEST_CASES)} tests passed ({accuracy:.1f}% accuracy)")
        print(f"{'=' * 60}")
        print("\nResults by category:")
        for category, results in category_results.items():
            cat_accuracy = (results["passed"] / results["total"]) * 100
            print(f"  {category.replace('_', ' ').title()}: {results['passed']}/{results['total']} ({cat_accuracy:.1f}%)")

        return {
            "total_tests": len(TEST_CASES),
            "passed": passed,
            "failed": failed,
            "accuracy": accuracy,
            "category_results": dict(category_results),
            "detailed_results": self.results,
        }

    def export_results(self, results, filename: str = "test_results.json"):
        export_data = {
            "summary": {
                "total_tests": results["total_tests"],
                "passed": results["passed"],
                "failed": results["failed"],
                "accuracy": results["accuracy"],
            },
            "category_results": results["category_results"],
            "detailed_results": results["detailed_results"],
        }
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2)
        print(f"\nResults exported to {filename}")


def main():
    print("ALARA Intent Classification Test Suite")
    print("=" * 60)

    try:
        IntentEngine()
    except Exception as e:
        print(f"Error initializing IntentEngine: {e}")
        print("Make sure GEMINI_API_KEY is set in your environment.")
        return

    suite = IntentTestSuite()
    results = suite.run_all_tests()
    suite.export_results(results)

    accuracy = results["accuracy"]
    if accuracy >= 90:
        print(f"\nEXCELLENT: {accuracy:.1f}% accuracy meets the 90% target.")
    elif accuracy >= 80:
        print(f"\nGOOD: {accuracy:.1f}% accuracy is close to the 90% target.")
    elif accuracy >= 70:
        print(f"\nNEEDS WORK: {accuracy:.1f}% accuracy is below the 90% target.")
    else:
        print(f"\nPOOR: {accuracy:.1f}% accuracy needs significant improvement.")

    print(f"\nTarget: 90%+ accuracy | Current: {accuracy:.1f}% | Gap: {90 - accuracy:.1f}%")


if __name__ == "__main__":
    main()

