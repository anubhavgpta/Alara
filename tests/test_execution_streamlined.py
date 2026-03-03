"""
Streamlined execution engine tests using pytest framework.

Run with:
    pytest tests/test_execution_streamlined.py
    pytest tests/test_execution_streamlined.py -v
    pytest tests/test_execution_streamlined.py::test_filesystem_capability
"""

import pytest
from pathlib import Path
from alara.capabilities.base import CapabilityResult


class TestFilesystemCapability:
    """Tests for filesystem capability."""

    def test_filesystem_initialization(self, alara_components):
        """Test filesystem capability initializes correctly."""
        fs = alara_components["filesystem"]
        assert fs is not None
        assert hasattr(fs, 'execute')
        assert hasattr(fs, 'supports')

    def test_filesystem_supported_operations(self, alara_components):
        """Test filesystem capability supports expected operations."""
        fs = alara_components["filesystem"]
        
        expected_operations = {
            "create_directory", "create_file", "write_file", "read_file",
            "delete_file", "delete_directory", "move_file", "copy_file",
            "list_directory", "search_files", "check_path_exists"
        }
        
        for op in expected_operations:
            assert fs.supports(op), f"Should support operation: {op}"
        
        assert not fs.supports("invalid_operation")

    def test_path_resolution(self, alara_components):
        """Test path resolution with various formats."""
        fs = alara_components["filesystem"]
        
        # Test user home expansion
        path1 = fs._resolve("~/test")
        assert path1.name == "test"
        
        # Test environment variable expansion
        path2 = fs._resolve("$env:USERPROFILE/Desktop/test")
        assert "Desktop" in str(path2)
        assert path2.name == "test"
        
        # Test HOME expansion
        path3 = fs._resolve("$HOME/Desktop/test")
        assert "Desktop" in str(path3)
        assert path3.name == "test"

    def test_create_and_delete_directory(self, alara_components, cleanup_desktop):
        """Test directory creation and deletion."""
        fs = alara_components["filesystem"]
        test_dir = "test_create_delete_dir"
        
        cleanup_desktop(test_dir)
        
        # Create directory
        result = fs.execute("create_directory", {"path": f"$env:USERPROFILE/Desktop/{test_dir}"})
        assert isinstance(result, CapabilityResult)
        assert result.success
        
        # Verify directory exists
        check_result = fs.execute("check_path_exists", {"path": f"$env:USERPROFILE/Desktop/{test_dir}"})
        assert check_result.success
        
        # Delete directory
        delete_result = fs.execute("delete_directory", {"path": f"$env:USERPROFILE/Desktop/{test_dir}"})
        assert delete_result.success

    def test_create_and_write_file(self, alara_components, cleanup_desktop):
        """Test file creation and writing."""
        fs = alara_components["filesystem"]
        test_file = "test_create_write_file.txt"
        test_content = "Hello, ALARA!"
        
        cleanup_desktop(test_file)
        
        # Create file
        result = fs.execute("create_file", {
            "path": f"$env:USERPROFILE/Desktop/{test_file}",
            "content": test_content
        })
        assert result.success
        
        # Read file back
        read_result = fs.execute("read_file", {"path": f"$env:USERPROFILE/Desktop/{test_file}"})
        assert read_result.success
        assert read_result.output == test_content

    def test_file_exists_error_handling(self, alara_components, cleanup_desktop):
        """Test error handling when file already exists."""
        fs = alara_components["filesystem"]
        test_file = "test_exists_error.txt"
        
        cleanup_desktop(test_file)
        
        # Create file first
        fs.execute("create_file", {"path": f"$env:USERPROFILE/Desktop/{test_file}"})
        
        # Try to create again - should fail
        result = fs.execute("create_file", {"path": f"$env:USERPROFILE/Desktop/{test_file}"})
        assert not result.success
        assert "already exists" in result.error

    def test_list_directory(self, alara_components):
        """Test directory listing."""
        fs = alara_components["filesystem"]
        
        # List current directory (should always exist)
        result = fs.execute("list_directory", {"path": "."})
        assert result.success
        assert result.output is not None


class TestCLICapability:
    """Tests for CLI capability."""

    def test_cli_initialization(self, alara_components):
        """Test CLI capability initializes correctly."""
        cli = alara_components["cli"]
        assert cli is not None
        assert hasattr(cli, 'execute')
        assert hasattr(cli, 'supports')
        assert cli.default_timeout_s > 0

    def test_cli_supported_operations(self, alara_components):
        """Test CLI capability supports expected operations."""
        cli = alara_components["cli"]
        
        assert cli.supports("run_command")
        assert not cli.supports("invalid_operation")

    def test_simple_command_execution(self, alara_components):
        """Test simple command execution."""
        cli = alara_components["cli"]
        
        # Test echo command (cross-platform)
        result = cli.execute("run_command", {"command": "echo Hello ALARA"})
        assert isinstance(result, CapabilityResult)
        assert result.success
        assert "Hello ALARA" in result.output
        assert result.metadata.get("returncode") == 0

    def test_command_with_working_directory(self, alara_components):
        """Test command execution with working directory."""
        cli = alara_components["cli"]
        
        # Run command in current directory
        result = cli.execute("run_command", {
            "command": "echo %CD%" if Path("C:").exists() else "echo $PWD",
            "working_dir": "."
        })
        assert result.success

    def test_invalid_command_handling(self, alara_components):
        """Test handling of invalid commands."""
        cli = alara_components["cli"]
        
        result = cli.execute("run_command", {"command": "nonexistent_command_12345"})
        assert not result.success
        assert result.metadata.get("returncode") != 0

    def test_missing_command_parameter(self, alara_components):
        """Test error handling for missing command parameter."""
        cli = alara_components["cli"]
        
        result = cli.execute("run_command", {})
        assert not result.success
        assert "command" in result.error.lower()


class TestSystemCapability:
    """Tests for system capability."""

    def test_system_initialization(self, alara_components):
        """Test system capability initializes correctly."""
        system = alara_components["system"]
        assert system is not None
        assert hasattr(system, 'execute')
        assert hasattr(system, 'supports')

    def test_system_supported_operations(self, alara_components):
        """Test system capability supports expected operations."""
        system = alara_components["system"]
        
        expected_operations = {"get_env_var", "set_env_var", "check_process"}
        
        for op in expected_operations:
            assert system.supports(op), f"Should support operation: {op}"
        
        assert not system.supports("invalid_operation")

    def test_environment_variable_operations(self, alara_components):
        """Test environment variable get/set operations."""
        system = alara_components["system"]
        
        # Set a test environment variable
        test_var = "ALARA_TEST_VAR"
        test_value = "test_value"
        
        set_result = system.execute("set_env_var", {
            "name": test_var,
            "value": test_value
        })
        assert set_result.success
        
        # Get the environment variable
        get_result = system.execute("get_env_var", {"name": test_var})
        assert get_result.success
        assert get_result.output == test_value

    def test_home_environment_variable(self, alara_components):
        """Test HOME environment variable handling."""
        system = alara_components["system"]
        
        # Get HOME (should resolve to user profile on Windows)
        result = system.execute("get_env_var", {"name": "HOME"})
        assert result.success
        assert result.output is not None
        assert Path(result.output).exists()

    def test_process_checking(self, alara_components):
        """Test process checking functionality."""
        system = alara_components["system"]
        
        # Check for a process that should exist on Windows
        result = system.execute("check_process", {"process_name": "explorer.exe"})
        # Explorer should be running on most Windows systems
        # But we don't fail the test if it's not (could be different system)
        assert isinstance(result, CapabilityResult)
        
        # Check for a process that definitely shouldn't exist
        fake_result = system.execute("check_process", {"process_name": "definitely_not_a_real_process_12345.exe"})
        assert not fake_result.success

    def test_missing_process_parameter(self, alara_components):
        """Test error handling for missing process parameter."""
        system = alara_components["system"]
        
        result = system.execute("check_process", {})
        assert not result.success
        assert "process_name" in result.error.lower()


class TestExecutionRouter:
    """Tests for execution router."""

    def test_router_initialization(self, alara_components):
        """Test execution router initializes correctly."""
        from alara.core.execution_router import ExecutionRouter
        
        router = ExecutionRouter()
        assert router is not None
        assert hasattr(router, 'route')
        assert router.filesystem is not None
        assert router.cli is not None
        assert router.system is not None

    def test_router_filesystem_routing(self, alara_components):
        """Test router routes filesystem operations correctly."""
        from alara.core.execution_router import ExecutionRouter
        from alara.schemas.task_graph import Step, StepType, ExecutionLayer
        
        router = ExecutionRouter()
        
        # Create a filesystem step
        step = Step(
            id=1,
            description="Test filesystem step",
            step_type=StepType.FILESYSTEM,
            preferred_layer=ExecutionLayer.OS_API,
            operation="check_path_exists",
            params={"path": "."},
            expected_outcome="Path exists",
            verification_method="none"
        )
        
        result = router.route(step)
        assert isinstance(result, CapabilityResult)
        assert result.success

    def test_router_cli_routing(self, alara_components):
        """Test router routes CLI operations correctly."""
        from alara.core.execution_router import ExecutionRouter
        from alara.schemas.task_graph import Step, StepType, ExecutionLayer
        
        router = ExecutionRouter()
        
        # Create a CLI step
        step = Step(
            id=1,
            description="Test CLI step",
            step_type=StepType.CLI,
            preferred_layer=ExecutionLayer.CLI,
            operation="run_command",
            params={"command": "echo test"},
            expected_outcome="Command executes",
            verification_method="check_exit_code_zero"
        )
        
        result = router.route(step)
        assert isinstance(result, CapabilityResult)
        assert result.success
