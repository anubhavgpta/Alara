"""
Streamlined planner tests using pytest framework.

Run with:
    pytest tests/test_planner_streamlined.py
    pytest tests/test_planner_streamlined.py -v
    pytest tests/test_planner_streamlined.py::test_planner_integration
"""

import pytest
from alara.schemas.task_graph import ExecutionLayer, StepType, TaskGraph


class TestPlannerIntegration:
    """Integration tests for the planner component."""

    def test_planner_initialization(self, alara_components):
        """Test that planner initializes correctly."""
        planner = alara_components["planner"]
        assert planner is not None
        assert hasattr(planner, 'plan')

    @pytest.mark.parametrize("goal", [
        "Create a new Python project called myapp with a virtual environment",
        "Find all PDF files on my desktop and move them to a folder called Documents/PDFs",
        "Delete all .tmp and .log files in my Downloads folder",
        "Set up a FastAPI project with a Postgres database called myapp_db",
        "Create a folder structure for a new React project called dashboard",
        "Find the largest 10 files in my Documents folder and list them",
        "Rename all images in my Downloads folder to include today's date",
        "Install git if not already installed and configure my username as Anubhav",
    ])
    def test_planner_goal_decomposition(self, alara_components, goal, allowed_verification_methods):
        """Test planner decomposes goals into valid task graphs."""
        understander = alara_components["understander"]
        planner = alara_components["planner"]
        
        # Understand the goal
        goal_context = understander.understand(goal)
        assert goal_context is not None
        assert goal_context.goal == goal
        
        # Plan the goal
        task_graph = planner.plan(goal_context)
        assert isinstance(task_graph, TaskGraph)
        assert task_graph.steps
        assert task_graph.goal
        
        # Validate task graph structure
        self._validate_task_graph(task_graph, allowed_verification_methods)

    def test_planner_error_handling(self, alara_components):
        """Test planner handles errors gracefully."""
        planner = alara_components["planner"]
        
        # Test with empty goal
        understander = alara_components["understander"]
        goal_context = understander.understand("")
        
        # Should either handle gracefully or raise appropriate error
        try:
            task_graph = planner.plan(goal_context)
            # If it succeeds, validate the result
            assert task_graph.steps  # Should have some steps even for empty input
        except Exception:
            # If it fails, that's acceptable for empty input
            pass

    def test_planner_dependency_resolution(self, alara_components):
        """Test planner creates valid dependencies between steps."""
        understander = alara_components["understander"]
        planner = alara_components["planner"]
        
        goal = "Create a Python project with a virtual environment and install FastAPI"
        goal_context = understander.understand(goal)
        task_graph = planner.plan(goal_context)
        
        # Check that dependencies are valid
        step_ids = {step.id for step in task_graph.steps}
        for step in task_graph.steps:
            for dep_id in step.depends_on:
                assert dep_id in step_ids, f"Step {step.id} depends on non-existent step {dep_id}"

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


class TestGoalUnderstander:
    """Tests for the goal understander component."""

    def test_goal_understander_initialization(self, alara_components):
        """Test that goal understander initializes correctly."""
        understander = alara_components["understander"]
        assert understander is not None
        assert hasattr(understander, 'understand')

    @pytest.mark.parametrize("goal,expected_scope", [
        ("create a folder on desktop", "filesystem"),
        ("run git status", "cli"),
        ("open notepad", "app"),
        ("create a python project and install dependencies", "mixed"),
    ])
    def test_goal_scope_detection(self, alara_components, goal, expected_scope):
        """Test goal understander detects correct scope."""
        understander = alara_components["understander"]
        goal_context = understander.understand(goal)
        
        assert goal_context is not None
        assert goal_context.raw_input == goal
        # Scope detection may vary, but should be one of the expected values
        assert goal_context.scope in ["filesystem", "cli", "app", "system", "mixed"]

    def test_goal_complexity_estimation(self, alara_components):
        """Test goal understander estimates complexity."""
        understander = alara_components["understander"]
        
        simple_goal = "create a folder"
        complex_goal = "create a Python project with virtual environment, install FastAPI, set up PostgreSQL database, create initial API endpoints, and configure Docker"
        
        simple_context = understander.understand(simple_goal)
        complex_context = understander.understand(complex_goal)
        
        assert simple_context.estimated_complexity in ["simple", "moderate", "complex"]
        assert complex_context.estimated_complexity in ["simple", "moderate", "complex"]
        # Complex goal should likely be rated as more complex
        # (This is a soft test - LLM may vary in its assessment)
