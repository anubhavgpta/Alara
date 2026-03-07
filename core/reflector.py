"""Reflection module for failure analysis and adaptive replanning."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import google.generativeai as genai
from loguru import logger

from alara.capabilities.base import CapabilityResult
from alara.schemas.task_graph import Step, TaskGraph


@dataclass
class ReflectionResult:
    action: str
    modified_step: Step | None = None
    reason: str = ""


class Reflector:
    """Analyze failed steps and propose recovery or replanning changes."""

    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY environment variable is required for reflection functionality"
            )
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.5-flash")

    def reflect(
        self,
        original_goal: str,
        task_graph: TaskGraph,
        failed_step: Step,
        capability_result: CapabilityResult,
        verification_result: Any,
        attempt_number: int,
    ) -> ReflectionResult:
        """Return a reflection result after failure analysis."""
        logger.info("Starting reflection for failed step {} after {} attempts", failed_step.id, attempt_number)
        
        try:
            prompt = self._build_reflection_prompt(
                original_goal, task_graph, failed_step, capability_result, verification_result, attempt_number
            )
            
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=2048,
                )
            )
            
            raw_response = response.text.strip()
            logger.debug("Raw reflection response: {}", raw_response)
            
            # Parse JSON response with fence stripping
            json_text = raw_response
            if json_text.startswith("```json"):
                json_text = json_text[7:]
            if json_text.endswith("```"):
                json_text = json_text[:-3]
            json_text = json_text.strip()
            
            parsed = json.loads(json_text)
            
            action = parsed.get("action", "escalate")
            reason = parsed.get("reason", "No reason provided")
            modified_step_data = parsed.get("modified_step")
            
            if action == "retry" and modified_step_data:
                # Create new step preserving original metadata
                new_step = Step(
                    id=failed_step.id,
                    step_type=modified_step_data.get("step_type", failed_step.step_type.value).lower(),
                    preferred_layer=modified_step_data.get("preferred_layer", failed_step.preferred_layer.value).lower(),
                    operation=modified_step_data.get("operation", failed_step.operation),
                    params=modified_step_data.get("params", failed_step.params),
                    description=modified_step_data.get("description", failed_step.description),
                    expected_outcome=modified_step_data.get("expected_outcome", failed_step.expected_outcome),
                    verification_method=modified_step_data.get("verification_method", failed_step.verification_method),
                    depends_on=failed_step.depends_on,
                    fallback_strategy=failed_step.fallback_strategy,
                    status=failed_step.status,
                    attempts=0,  # Reset attempts for retry
                    error=failed_step.error,
                    result=failed_step.result,
                )
                
                logger.info("Reflector modified step {}: {}", failed_step.id, reason)
                return ReflectionResult(action="retry", modified_step=new_step, reason=reason)
            
            elif action == "skip":
                logger.info("Reflector skipped step {}: {}", failed_step.id, reason)
                return ReflectionResult(action="skip", modified_step=None, reason=reason)
            
            else:  # escalate or unknown
                logger.warning("Reflector escalated step {}: {}", failed_step.id, reason)
                return ReflectionResult(action="escalate", modified_step=None, reason=reason)
                
        except Exception as exc:
            logger.error("Reflection failed for step {}: {}", failed_step.id, exc)
            return ReflectionResult(
                action="escalate",
                modified_step=None,
                reason=f"Reflection failed: {str(exc)}"
            )

    def _build_reflection_prompt(
        self,
        original_goal: str,
        task_graph: TaskGraph,
        failed_step: Step,
        capability_result: CapabilityResult,
        verification_result: Any,
        attempt_number: int,
    ) -> str:
        """Build the reflection prompt for Gemini."""
        
        # Build task summary
        steps_summary = []
        for step in task_graph.steps:
            status_icon = "[DONE]" if step.status.value == "done" else "[FAIL]" if step.status.value == "failed" else "[PENDING]"
            steps_summary.append(f"{status_icon} Step {step.id}: {step.description} ({step.operation})")
        
        prompt = f"""You are ALARA's reflection module. A step has failed after multiple attempts and you need to decide what to do.

ORIGINAL GOAL:
{original_goal}

TASK PLAN SUMMARY:
{chr(10).join(steps_summary)}

FAILED STEP DETAILS:
Step ID: {failed_step.id}
Description: {failed_step.description}
Operation: {failed_step.operation}
Parameters: {json.dumps(failed_step.params, indent=2)}
Expected Outcome: {failed_step.expected_outcome}
Verification Method: {failed_step.verification_method}

EXECUTION ATTEMPT DETAILS:
Attempt Number: {attempt_number}
Capability Output: {capability_result.output or "No output"}
Capability Error: {capability_result.error or "No error"}
Capability Success: {capability_result.success}
Verification Result: {getattr(verification_result, 'detail', 'No verification detail')}
Verification Passed: {getattr(verification_result, 'passed', 'Unknown')}

ANALYSIS:
The step failed verification after execution. This could be due to:
1. Wrong parameters or approach
2. Environment-specific issues  
3. Incorrect assumptions about the system state
4. Timing issues or race conditions

YOUR TASK:
Choose ONE of the following actions and provide a modified step if retrying:

1. "retry" - Modify the step with a different approach/parameters
2. "skip" - Skip this step if it's non-critical to the overall goal
3. "escalate" - Escalate to human user if unrecoverable

RESPONSE FORMAT (JSON only, no explanations outside JSON):
{{
  "action": "retry" | "skip" | "escalate",
  "reason": "detailed explanation of your decision",
  "modified_step": {{
    "step_type": "filesystem|cli|system|app_adapter|vision",
    "preferred_layer": "os_api|app_adapter|cli|vision", 
    "operation": "operation_name",
    "params": {{}},
    "description": "what this step does",
    "expected_outcome": "expected result",
    "verification_method": "how to verify"
  }} | null
}}

Think carefully about what went wrong and provide a concrete solution if retrying."""
        
        return prompt
