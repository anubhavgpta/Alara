"""
Simple test runner for ALARA test suite.

Run with:
    python tests/run_tests.py
    python tests/run_tests.py --category planner
    python tests/run_tests.py --verbose
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list, verbose: bool = False) -> tuple[int, str, str]:
    """Run a command and return exit code, stdout, stderr."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent
        )
        
        if verbose:
            print(f"Running: {' '.join(cmd)}")
            if result.stdout:
                print(f"STDOUT:\n{result.stdout}")
            if result.stderr:
                print(f"STDERR:\n{result.stderr}")
        
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def run_pytest_tests(category: str = None, verbose: bool = False) -> bool:
    """Run pytest-based tests."""
    print("Running pytest tests...")
    
    cmd = [sys.executable, "-m", "pytest", "tests/"]
    
    if category:
        if category == "planner":
            cmd.append("tests/test_planner_streamlined.py")
        elif category == "execution":
            cmd.append("tests/test_execution_streamlined.py")
        elif category == "integration":
            cmd.append("tests/test_suite.py::TestALARATestSuite::_test_integration_components")
    
    if verbose:
        cmd.append("-v")
    
    exit_code, stdout, stderr = run_command(cmd, verbose)
    
    if exit_code == 0:
        print("Pytest tests passed")
        return True
    else:
        print("Pytest tests failed")
        if stderr:
            print(f"Errors: {stderr}")
        return False


def run_legacy_tests(category: str = None, verbose: bool = False) -> bool:
    """Run legacy test files."""
    print("Running legacy tests...")
    
    test_files = {
        "planner": "tests/test_planner.py",
        "intent": "tests/test_intent.py", 
        "integration": "tests/test_week56_integrations.py"
    }
    
    if category:
        test_files = {k: v for k, v in test_files.items() if k == category}
    
    all_passed = True
    
    for test_name, test_file in test_files.items():
        print(f"  Running {test_name} tests...")
        cmd = [sys.executable, "-m", test_file.replace("/", ".")]
        
        exit_code, stdout, stderr = run_command(cmd, verbose)
        
        if exit_code == 0:
            print(f"    {test_name} tests passed")
        else:
            print(f"    {test_name} tests failed")
            if verbose and stderr:
                print(f"    Errors: {stderr}")
            all_passed = False
    
    return all_passed


def run_unified_suite(category: str = None, verbose: bool = False) -> bool:
    """Run unified test suite."""
    print("Running unified test suite...")
    
    cmd = [sys.executable, "-m", "tests.test_suite"]
    
    if category:
        cmd.extend(["--category", category])
    
    if verbose:
        cmd.append("--debug")
    
    exit_code, stdout, stderr = run_command(cmd, verbose)
    
    if exit_code == 0:
        print("Unified test suite passed")
        return True
    else:
        print("Unified test suite failed")
        if stdout:
            print(f"Output: {stdout}")
        if stderr:
            print(f"Errors: {stderr}")
        return False


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="ALARA Test Runner")
    parser.add_argument("--category", choices=["planner", "execution", "integration", "intent"],
                       help="Run specific test category")
    parser.add_argument("--framework", choices=["pytest", "legacy", "unified", "all"],
                       default="all", help="Test framework to use")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--output", help="Save results to file")
    
    args = parser.parse_args()
    
    print("ALARA Test Runner")
    print("=" * 50)
    
    results = {}
    
    # Run tests based on framework choice
    if args.framework in ["pytest", "all"]:
        results["pytest"] = run_pytest_tests(args.category, args.verbose)
    
    if args.framework in ["legacy", "all"]:
        results["legacy"] = run_legacy_tests(args.category, args.verbose)
    
    if args.framework in ["unified", "all"]:
        results["unified"] = run_unified_suite(args.category, args.verbose)
    
    # Print summary
    print("\n" + "=" * 50)
    print("TEST SUMMARY")
    print("=" * 50)
    
    for framework, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"{status} {framework.title()}: {'PASSED' if passed else 'FAILED'}")
    
    overall_success = all(results.values())
    print(f"\nOverall: {'PASSED' if overall_success else 'FAILED'}")
    
    # Save results if requested
    if args.output:
        import json
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {args.output}")
    
    sys.exit(0 if overall_success else 1)


if __name__ == "__main__":
    main()
