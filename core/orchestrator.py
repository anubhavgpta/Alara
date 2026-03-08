"""Top-level orchestration loop for ALARA plan-execute-verify-reflect workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from alara.capabilities.base import CapabilityResult
from alara.core.execution_router import ExecutionRouter
from alara.core.reflector import ReflectionResult, Reflector
from alara.core.verifier import VerificationResult, Verifier
from alara.schemas.task_graph import StepStatus, TaskGraph


@dataclass
class OrchestratorResult:
    success: bool
    steps_completed: int
    steps_failed: int
    steps_skipped: int
    total_steps: int
    message: str
    execution_log: list[dict[str, Any]]


class Orchestrator:
    """Coordinate goal understanding, planning, execution, verification, and reflection."""

    MAX_RETRIES = 3

    def __init__(self) -> None:
        """Initialize orchestrator dependencies."""
        self.router = ExecutionRouter()
        self.verifier = Verifier()
        self.reflector = Reflector()
        self._last_execution_log = []

    def run(self, task_graph: TaskGraph, progress_callback=None) -> OrchestratorResult:
        """Run the orchestration loop for a single task graph."""
        logger.info("Starting orchestration for task: {}", task_graph.goal)
        task_graph.status = "running"
        execution_log = []

        while not task_graph.is_complete() and not task_graph.is_failed():
            step = task_graph.next_pending_step()
            if not step:
                # No pending steps with satisfied dependencies - likely due to failures
                logger.warning("No executable steps available, ending orchestration")
                break

            step.status = StepStatus.RUNNING
            logger.info("Executing step {}: {} — {}", step.id, step.operation, step.description)

            try:
                # Resolve code edit placeholders if needed
                if step.operation == "edit_file":
                    step = self._resolve_code_edit(step, execution_log)
                
                # Execute step
                capability_result = self.router.route(step)
                step.attempts += 1

                # Verify result only if capability succeeded
                if not capability_result.success:
                    # Skip verification — capability already failed
                    verification_result = VerificationResult(
                        passed=False,
                        method="capability_failed",
                        detail=capability_result.error or "Capability failed"
                    )
                else:
                    # Run normal verification
                    verification_result = self.verifier.verify(step, capability_result)

                # Log attempt
                attempt_log = self._log_step_attempt(step, capability_result, verification_result, step.attempts)
                execution_log.append(attempt_log)

                if verification_result.passed:
                    # Step succeeded
                    step.status = StepStatus.DONE
                    from alara.schemas.task_graph import StepResult, ExecutionLayer
                    step_result = StepResult(
                        step_id=step.id,
                        success=True,
                        output=capability_result.output,
                        error=capability_result.error,
                        verified=True,
                        execution_layer_used=ExecutionLayer.OS_API,  # Default for now
                        duration_ms=0,  # TODO: add timing
                        attempts=step.attempts,
                    )
                    task_graph.results.append(step_result)
                    
                    logger.info("Step {} completed successfully", step.id)
                    if progress_callback:
                        progress_callback(step, step_result)
                else:
                    # Step failed verification
                    logger.warning(
                        "Step {} failed verification: {} | {}",
                        step.id,
                        step.operation,
                        verification_result.detail
                    )

                    if step.attempts >= self.MAX_RETRIES:
                        if step.fallback_strategy == "skip_optional":
                            step.status = StepStatus.SKIPPED
                            logger.info("Skipping optional step {}", step.id)
                            continue
                        else:
                            # Use reflector to decide next action
                            reflection = self.reflector.reflect(
                                original_goal=task_graph.goal,
                                task_graph=task_graph,
                                failed_step=step,
                                capability_result=capability_result,
                                verification_result=verification_result,
                                attempt_number=step.attempts,
                            )

                            if reflection.action == "retry" and reflection.modified_step:
                                # Apply modified step to current step
                                step.operation = reflection.modified_step.operation
                                step.params = reflection.modified_step.params
                                step.description = reflection.modified_step.description
                                step.expected_outcome = reflection.modified_step.expected_outcome
                                step.verification_method = reflection.modified_step.verification_method
                                step.step_type = reflection.modified_step.step_type
                                step.preferred_layer = reflection.modified_step.preferred_layer
                                step.attempts = 0  # Reset attempts
                                step.status = StepStatus.PENDING
                                logger.info("Reflector modified step {}: {}", step.id, reflection.reason)
                                continue

                            elif reflection.action == "skip":
                                step.status = StepStatus.SKIPPED
                                logger.info("Reflector skipped step {}: {}", step.id, reflection.reason)
                                continue

                            else:  # escalate
                                step.status = StepStatus.FAILED
                                step.error = reflection.reason
                                logger.error("Step {} escalated: {}", step.id, reflection.reason)
                                break
                    else:
                        # Retry the step
                        step.status = StepStatus.PENDING
                        logger.info(
                            "Retrying step {} (attempt {}/{})",
                            step.id,
                            step.attempts,
                            self.MAX_RETRIES
                        )
                        continue

            except Exception as exc:
                logger.error("Unexpected exception during step {}: {}", step.id, exc)
                step.status = StepStatus.FAILED
                step.error = str(exc)
                step.attempts += 1
                
                attempt_log = self._log_step_attempt(
                    step,
                    CapabilityResult.fail(error=str(exc)),
                    VerificationResult(False, "exception", f"Exception: {exc}"),
                    step.attempts,
                )
                execution_log.append(attempt_log)
                break

        # Determine final status
        if all(step.status in {StepStatus.DONE, StepStatus.SKIPPED} for step in task_graph.steps):
            task_graph.status = "done"
        else:
            task_graph.status = "failed"

        # Build result
        steps_completed = sum(1 for step in task_graph.steps if step.status == StepStatus.DONE)
        steps_failed = sum(1 for step in task_graph.steps if step.status == StepStatus.FAILED)
        steps_skipped = sum(1 for step in task_graph.steps if step.status == StepStatus.SKIPPED)

        success = task_graph.status == "done"
        message = (
            f"Task completed successfully - {steps_completed}/{len(task_graph.steps)} steps"
            if success
            else f"Task failed - {steps_completed}/{len(task_graph.steps)} steps completed"
        )

        logger.info("Orchestration finished: {}", message)

        # Store execution log for chain context
        self._last_execution_log = execution_log.copy()

        return OrchestratorResult(
            success=success,
            steps_completed=steps_completed,
            steps_failed=steps_failed,
            steps_skipped=steps_skipped,
            total_steps=len(task_graph.steps),
            message=message,
            execution_log=execution_log,
        )

    @property
    def last_execution_log(self) -> list:
        return self._last_execution_log

    def _log_step_attempt(
        self,
        step: Any,
        capability_result: CapabilityResult,
        verification_result: VerificationResult,
        attempt: int,
    ) -> dict[str, Any]:
        """Log a step attempt for the execution log."""
        return {
            "step_id": step.id,
            "operation": step.operation,
            "description": step.description,
            "attempt": attempt,
            "success": capability_result.success,
            "output": capability_result.output,
            "error": capability_result.error,
            "verified": verification_result.passed,
            "verification_detail": verification_result.detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _resolve_code_edit(self, step: Any, execution_log: list[dict[str, Any]]) -> Any:
        """
        For edit_file steps with <<READ_FIRST>> placeholders,
        substitute the actual file content from the most
        recent successful read_file step in execution_log.
        """
        from alara.schemas.task_graph import Step
        
        # Only act on edit_file steps with the placeholder
        if not isinstance(step, Step) or step.operation != "edit_file":
            return step
        
        old_content = step.params.get("old_content", "")
        new_content = step.params.get("new_content", "")
        
        has_placeholder = (
            "<<READ_FIRST" in old_content or
            "<<READ_FIRST" in new_content
        )
        if not has_placeholder:
            return step
        
        # Find the most recent successful read_file step
        # targeting the same file path
        target_path = step.params.get("path", "")
        file_content = None
        
        for log_entry in reversed(execution_log):
            if not log_entry.get("success"):
                continue
            if log_entry.get("operation") not in (
                "read_file", "analyze_structure"
            ):
                continue
            # Accept if same path OR if no path info
            # available (take most recent read regardless)
            log_output = log_entry.get("output", "")
            if log_output:
                file_content = log_output
                break
        
        if file_content is None:
            # No read step found — return step unchanged
            # and let the capability return "not found"
            # which will trigger reflection naturally
            return step
        
        # Replace placeholder in old_content:
        # The placeholder in old_content represents the
        # ANCHOR — text we want to find and replace.
        # For "add to end of file" patterns where
        # old_content IS the placeholder, use the last
        # non-empty line of the file as an anchor.
        
        if old_content.strip() == "<<READ_FIRST: use content from step 1 output>>":
            # Anchor = last meaningful line of file
            lines = [
                l for l in file_content.splitlines()
                if l.strip()
            ]
            anchor = lines[-1] if lines else file_content[-100:]
            step.params["old_content"] = anchor
        else:
            step.params["old_content"] = old_content.replace(
                "<<READ_FIRST: use content from step 1 output>>",
                file_content
            )
        
        # Replace placeholder in new_content:
        # new_content typically contains the anchor
        # PLUS new code to append after it.
        # Substitute the anchor correctly.
        if "<<READ_FIRST: use content from step 1 output>>" in new_content:
            anchor = step.params["old_content"]
            step.params["new_content"] = new_content.replace(
                "<<READ_FIRST: use content from step 1 output>>",
                anchor
            )
        
        return step
