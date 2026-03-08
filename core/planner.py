"""Planning module for converting goal context into a task graph via Gemini."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google import genai
from loguru import logger

from alara.schemas.goal import GoalContext
from alara.schemas.task_graph import Step, TaskGraph
from alara.memory.models import MemoryContext


class PlanningError(Exception):
    """Raised when planning fails due to model or schema issues."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class Planner:
    """Generate a task graph from a parsed GoalContext."""

    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GEMINI_API_KEY not set. Get a free key at "
                "https://aistudio.google.com and add it to .env"
            )

        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.system_prompt = self._build_system_prompt()
        self.last_raw_response: str | None = None
        self._last_approach_response: str | None = None

        self.client = genai.Client(api_key=api_key)

        logger.info("Planner initialized successfully with model={}", self.model_name)

    def plan(self, goal_context: GoalContext, memory_context: MemoryContext | None = None, code_context: str | None = None, chain_context: str | None = None) -> TaskGraph:
        logger.info(
            "Planning started | goal='{}' | complexity={}",
            goal_context.goal,
            goal_context.estimated_complexity,
        )

        approach_context = ""
        
        if goal_context.estimated_complexity == "complex":
            logger.info("Complex goal detected — running two-pass planning")
            approach_context = self._build_approach(goal_context, memory_context)
            if approach_context:
                logger.debug(f"Pass 1 approach built: {len(approach_context)} chars")
            else:
                logger.warning("Pass 1 failed — falling back to single-pass planning")

        user_message = self._build_user_message(goal_context, memory_context, code_context, approach_context, chain_context)
        raw_response = self._call_gemini(user_message)
        parsed_steps = self._parse_response(raw_response)

        parsed_ids: set[int] = set()
        for item in parsed_steps:
            if isinstance(item, dict) and isinstance(item.get("id"), int):
                parsed_ids.add(item["id"])

        normalized_step_dicts: list[dict[str, Any]] = []
        for raw_step in parsed_steps:
            step_dict = dict(raw_step)
            depends_on = step_dict.get("depends_on", [])
            if isinstance(depends_on, list):
                filtered = [dep for dep in depends_on if dep in parsed_ids]
                removed = [dep for dep in depends_on if dep not in parsed_ids]
                if removed:
                    logger.warning(
                        "Removed invalid depends_on references {} from step id={}",
                        removed,
                        step_dict.get("id"),
                    )
                step_dict["depends_on"] = filtered
            normalized_step_dicts.append(step_dict)

        errors: list[str] = []
        validated_steps: list[Step] = []
        for index, step_dict in enumerate(normalized_step_dicts, start=1):
            try:
                validated_steps.append(Step.model_validate(step_dict))
            except Exception as exc:
                errors.append(f"step[{index}] validation failed: {exc}")

        if errors:
            message = "Invalid steps returned by planner:\n" + "\n".join(errors)
            logger.error(message)
            raise PlanningError(message)

        if len(validated_steps) > 10 and all(not step.depends_on for step in validated_steps):
            logger.warning(
                "Planner produced {} steps with no dependencies - this may indicate a planning error",
                len(validated_steps),
            )

        logger.debug("Parsed planning JSON: {}", normalized_step_dicts)

        task_graph = TaskGraph(
            goal=goal_context.goal,
            goal_context=goal_context,
            steps=validated_steps,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="pending",
            results=[],
        )

        logger.info("Planning succeeded | steps={}", len(task_graph.steps))
        logger.debug(
            "TaskGraph details | created_at={} | step_ids={}",
            task_graph.created_at,
            [s.id for s in task_graph.steps],
        )
        return task_graph

    @property
    def last_approach_response(self) -> str | None:
        return self._last_approach_response

    def _build_approach(self, goal_context: GoalContext, memory_context: MemoryContext | None) -> str:
        """Run Pass 1 for complex goals to generate a structured approach outline."""
        try:
            logger.debug("Starting Pass 1 approach building")
            
            # Build Pass 1 system prompt
            approach_system_prompt = (
                "You are a senior software engineer planning how to accomplish a complex goal on a Windows machine.\n\n"
                "Your job is to think through the approach and produce a structured outline that will guide step generation.\n\n"
                "STEP GENERATION RULES:\n\n"
                "- NEVER generate guard-check steps (check_path_exists before create)\n"
                "- NEVER generate server start steps (uvicorn, npm start)\n"
                "- NEVER generate HTTP test steps (curl requests)\n"
                "- Final step should be create_file or pip install\n\n"
                "OPERATION RULES:\n\n"
                "- The operation \"write_file\" does not exist. NEVER use it.\n\n"
                "- To create a new file with content, use step_type=\"filesystem\", operation=\"create_file\" with a \"content\" param.\n\n"
                "- To overwrite an existing file with new content, use step_type=\"filesystem\", operation=\"create_file\" — it overwrites if the file already exists.\n\n"
                "- To append to a file, use step_type=\"code\", operation=\"append_to_file\".\n\n"
                "- To make surgical edits to a file, use step_type=\"code\", operation=\"edit_file\" with old_content and new_content params.\n\n"
                "- Never invent operation names not in this list:\n"
                "  filesystem: create_directory, create_file, delete_file, move_file, copy_file, check_path_exists, list_directory\n"
                "  cli: run_command\n"
                "  code: read_file, read_lines, analyze_structure, edit_file, append_to_file, insert_after_line, summarize_file, scan_project, check_contains\n\n"
                "For the given goal, produce a JSON object with these fields. Keep descriptions brief:\n\n"
                "{\n"
                "  \"goal_restatement\": \"brief restatement\",\n"
                "  \"approach_summary\": \"1-2 sentence description\",\n"
                "  \"phases\": [\n"
                "    {\n"
                "      \"phase\": \"Phase name\",\n"
                "      \"purpose\": \"What this phase accomplishes\",\n"
                "      \"key_operations\": [\"op1\", \"op2\"],\n"
                "      \"dependencies\": [\"what must be true\"],\n"
                "      \"risks\": [\"what could go wrong\"]\n"
                "    }\n"
                "  ],\n"
                "  \"critical_paths\": [\"absolute path 1\", \"absolute path 2\"],\n"
                "  \"assumptions\": [\"assumption 1\", \"assumption 2\"],\n"
                "  \"estimated_steps\": number\n"
                "}\n\n"
                "Use Windows platform context. All paths must be absolute. Respond with JSON only. No markdown."
            )
            logger.debug("Pass 1: System prompt built, length: {}", len(approach_system_prompt))
            
            # Build Pass 1 user message
            base_message = self._build_user_message(goal_context, memory_context)
            approach_user_message = f"Plan the approach for this goal:\n\n{base_message}"
            logger.debug("Pass 1: User message built, length: {}", len(approach_user_message))
            
            # Call Gemini for Pass 1
            response = self._generate_content_for_approach(approach_user_message, approach_system_prompt)
            self._last_approach_response = response
            logger.debug("Pass 1: Got response, storing it")
            
            # Validate JSON
            try:
                # Handle markdown code fences like the main parser does
                response_text = response.strip()
                if response_text.startswith("```"):
                    lines = response_text.splitlines()
                    if lines and lines[0].strip().startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    response_text = "\n".join(lines).strip()
                
                approach_data = json.loads(response_text)
                logger.debug("Pass 1: JSON parsed successfully")
                
                # Log warning if estimated_steps > 15
                if isinstance(approach_data.get("estimated_steps"), int) and approach_data["estimated_steps"] > 15:
                    logger.warning(
                        "Complex goal may exceed single TaskGraph capacity — consider goal chaining"
                    )
                
                logger.debug("Pass 1: Approach building completed successfully")
                return response
            except json.JSONDecodeError as exc:
                logger.warning(f"Pass 1 failed to parse JSON: {exc}")
                logger.debug("Pass 1: Raw response was: {}", repr(response))
                return ""
                
        except Exception as exc:
            logger.warning(f"Pass 1 failed: {exc}")
            return ""

    def _generate_content_for_approach(self, message: str, system_prompt: str) -> str:
        """Generate content for Pass 1 with approach-specific settings."""
        try:
            logger.debug("Pass 1: Generating content with message length: {}", len(message))
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=message,
                config=genai.types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.3,
                    max_output_tokens=4096
                )
            )
            text = (getattr(response, "text", None) or "").strip()
            logger.debug("Pass 1: Got response length: {}", len(text))
            if not text:
                exc = ValueError("Pass 1 Gemini returned an empty response")
                logger.error("Pass 1 Gemini returned an empty response")
                raise PlanningError("Pass 1 Gemini returned an empty response", cause=exc)
            return text
        except Exception as exc:
            logger.error("Pass 1 Gemini API call failed: {}", exc)
            raise PlanningError(f"Pass 1 Gemini API call failed: {exc}", cause=exc) from exc

    def _call_gemini(self, user_message: str) -> str:
        retry_suffix = (
            "\n\nYour previous response was not valid JSON. Return ONLY the JSON object. "
            "No markdown, no explanation, no code fences."
        )

        first_response_text = self._generate_content(user_message)
        self.last_raw_response = first_response_text
        try:
            self._parse_response(first_response_text)
            return first_response_text
        except PlanningError:
            logger.warning("First parse attempt failed, retrying with stricter instruction.")
            logger.debug("Raw response attempt 1: {}", first_response_text)

        second_message = f"{user_message}{retry_suffix}"
        second_response_text = self._generate_content(second_message)
        self.last_raw_response = second_response_text
        try:
            self._parse_response(second_response_text)
            return second_response_text
        except PlanningError as second_parse_error:
            logger.debug("Raw response attempt 2: {}", second_response_text)
            logger.error("Gemini returned malformed JSON after 2 attempts")
            raise PlanningError(
                "Gemini returned malformed JSON after 2 attempts",
                cause=second_parse_error,
            ) from second_parse_error

    def _generate_content(self, message: str) -> str:
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=message,
                config=genai.types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    temperature=0.2
                )
            )
        except Exception as exc:
            logger.error("Gemini API call failed: {}", exc)
            raise PlanningError(f"Gemini API call failed: {exc}", cause=exc) from exc

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            exc = ValueError("Gemini returned an empty response")
            logger.error("Gemini returned an empty response")
            raise PlanningError("Gemini returned an empty response", cause=exc)
        return text

    def _parse_response(self, raw: str) -> list[dict]:
        if raw is None:
            raise PlanningError("Invalid JSON from Gemini: response was None")

        body = raw.strip()
        if not body:
            raise PlanningError("Invalid JSON from Gemini: response was empty or whitespace")

        if body.lower() in {"null", "undefined"}:
            raise PlanningError(f"Invalid JSON from Gemini: response was {body!r}")

        if body.startswith("```"):
            lines = body.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            body = "\n".join(lines).strip()

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise PlanningError(f"Invalid JSON from Gemini: {exc}", cause=exc) from exc

        if isinstance(parsed, list):
            steps = parsed
        elif isinstance(parsed, dict) and "steps" in parsed:
            steps = parsed["steps"]
        else:
            raise PlanningError("Unexpected response shape: expected steps array")

        if not isinstance(steps, list):
            raise PlanningError("Unexpected response shape: expected steps array")
        if not steps:
            raise PlanningError("Gemini returned an empty steps array")

        NORMALISE_KEYS = {"step_type", "preferred_layer"}
        for step in steps:
            for key in NORMALISE_KEYS:
                if key in step and isinstance(step[key], str):
                    step[key] = step[key].lower()

        return steps

    def _build_user_message(self, goal_context: GoalContext, memory_context: MemoryContext | None, code_context: str | None = None, approach_context: str | None = None, chain_context: str | None = None) -> str:
        message = (
            f"Platform: Windows 10/11\n"
            f"Shell: PowerShell\n"
            f"Package manager: winget\n"
            f"Path separator: \\\n"
            f"Home directory variable: $env:USERPROFILE\n"
            f"User home directory (absolute): {Path.home().as_posix()}\n"
            f"Common user directories:\n"
            f"  Desktop    -> {(Path.home() / 'Desktop').as_posix()}\n"
            f"  Documents  -> {(Path.home() / 'Documents').as_posix()}\n"
            f"  Downloads  -> {(Path.home() / 'Downloads').as_posix()}\n"
            f"  Pictures   -> {(Path.home() / 'Pictures').as_posix()}\n"
            f"  Videos     -> {(Path.home() / 'Videos').as_posix()}\n"
            f"  Music      -> {(Path.home() / 'Music').as_posix()}\n"
            f"  AppData    -> {(Path.home() / 'AppData').as_posix()}\n"
            f"\n"
            f"Goal: {goal_context.goal}\n"
            f"Scope: {goal_context.scope}\n"
            f"Constraints: "
            f"{', '.join(goal_context.constraints) or 'none'}\n"
            f"Working directory: "
            f"{goal_context.working_directory or 'not specified'}\n"
            f"Complexity: {goal_context.estimated_complexity}\n"
        )
        
        # Add memory context if provided
        if memory_context is not None:
            message += f"\n{memory_context.summary}\n"
            
            # Fallback: If Last executed paths is missing but we have recent goals, add it manually
            if "Last executed paths" not in memory_context.summary and memory_context.recent_goals:
                last_paths_text = "Last executed paths:\n"
                for entry in memory_context.recent_goals[:3]:
                    if entry.status == "success" and entry.execution_log:
                        for log in entry.execution_log:
                            detail = log.get("verification_detail", "")
                            if detail.startswith("Path exists:"):
                                path = detail.replace("Path exists:", "").strip()
                                path = path.replace("\\", "/")
                                last_paths_text += f"  {entry.goal[:55]} → {path}\n"
                                break
                if last_paths_text != "Last executed paths:\n":  # Only add if we found paths
                    message += f"\n{last_paths_text}\n"
        
        # Add chain context if provided
        if chain_context and chain_context.strip():
            message += f"\n{chain_context}\n"
        
        # Add approach context if provided (Pass 1 output)
        if approach_context and approach_context.strip():
            message += f"\n=== APPROACH CONTEXT (from Pass 1 analysis) ===\n\n"
            message += f"This goal was analyzed in a prior planning pass. "
            message += f"Use the following structured approach to guide your step generation. "
            message += f"Follow the phases, use the critical paths exactly as specified, and account for the identified risks.\n\n"
            message += f"{approach_context}\n\n"
            message += f"=== END APPROACH CONTEXT ===\n"
        
        # Add code context if provided
        if code_context and code_context.strip():
            message += f"\n{code_context}\n"
        
        return message

    def _build_system_prompt(self) -> str:
        return (
            "You are ALARA's planning engine. Analyze the goal and produce atomic, executable steps only.\n"
            "Atomic means each step does exactly one thing. Do not combine multiple actions in one step.\n\n"
            "IMPORTANT: An APPROACH CONTEXT is included in the user message. This was produced by a prior analysis pass. You MUST:\n"
            "1. Follow the phases described in the approach\n"
            "2. Use the exact critical_paths listed — do not invent alternative paths\n"
            "3. Account for each identified risk with either a verification step or a fallback_strategy\n"
            "4. Generate at least the estimated_steps count if the approach warrants it\n"
            "5. If the approach has multiple phases, ensure steps are ordered to respect phase dependencies\n\n"
            "IMPORTANT: If a CHAIN CONTEXT is included showing previously completed goals in this session, use the paths and outputs from prior goals when relevant — do not recreate work that was already done. If a prior goal created a directory or file that this goal needs, use that exact path.\n\n"
            "STEP GENERATION RULES:\n\n"
            "- NEVER generate a step whose sole purpose is to check whether a path or resource exists before creating it. Use create_directory and create_file directly — they are idempotent and handle the \"already exists\" case gracefully. A check_path_exists step as a guard is always wrong because it will fail when the path does not yet exist, causing unnecessary retries.\n\n"
            "- NEVER generate steps that start a long-running server process (e.g. uvicorn, npm start, python manage.py runserver). These block execution and cannot be verified. Stop the plan at \"project is built and ready to run.\"\n\n"
            "- NEVER generate steps that test a running server with curl or HTTP requests. These require a live server and dynamic values (tokens, IDs) that cannot be known at planning time. Stop at \"project files are complete.\"\n\n"
            "- The final step of any scaffold plan should be a create_file or run_command (pip install or pip freeze) — never a server start or HTTP test.\n\n"
            "OPERATION RULES:\n\n"
            "- The operation \"write_file\" does not exist. NEVER use it.\n\n"
            "- To create a new file with content, use step_type=\"filesystem\", operation=\"create_file\" with a \"content\" param.\n\n"
            "- To overwrite an existing file with new content, use step_type=\"filesystem\", operation=\"create_file\" — it overwrites if the file already exists.\n\n"
            "- To append to a file, use step_type=\"code\", operation=\"append_to_file\".\n\n"
            "- To make surgical edits to a file, use step_type=\"code\", operation=\"edit_file\" with old_content and new_content params.\n\n"
            "- Never invent operation names not in this list:\n"
            "  filesystem: create_directory, create_file, delete_file, move_file, copy_file, check_path_exists, list_directory\n"
            "  cli: run_command\n"
            "  code: read_file, read_lines, analyze_structure, edit_file, append_to_file, insert_after_line, summarize_file, scan_project, check_contains\n\n"
            "Only use these operations:\n"
            "Filesystem:\n"
            "  create_directory  params: { path }\n"
            "  create_file       params: { path, content }\n"
            "  write_file        params: { path, content }\n"
            "  read_file         params: { path }\n"
            "  delete_file       params: { path }\n"
            "  move_file         params: { source, destination }\n"
            "  copy_file         params: { source, destination }\n"
            "  list_directory    params: { path }\n"
            "  search_files      params: { path, pattern }\n"
            "  check_path_exists params: { path }\n"
            "CLI:\n"
            "  run_command       params: { command, working_dir }\n"
            "App:\n"
            "  open_app          params: { app_name, args: [] }\n"
            "  close_app         params: { app_name }\n"
            "  focus_app         params: { app_name }\n"
            "System:\n"
            "  check_process     params: { process_name }\n"
            "  get_env_var       params: { name }\n"
            "  set_env_var       params: { name, value }\n"
            "Code:\n"
            "  read_file         params: { path }\n"
            "  read_lines        params: { path, start, end }\n"
            "  analyze_structure  params: { path }\n"
            "  edit_file         params: { path, old_content, new_content }\n"
            "  append_to_file    params: { path, content }\n"
            "  insert_after_line params: { path, line_number, content }\n"
            "  summarize_file    params: { path, max_lines }\n"
            "  scan_project      params: { root, extensions, max_files, exclude_dirs }\n"
            "  check_contains    params: { path, search }\n\n"
            "Only use these verification_method values:\n"
            "  check_path_exists\n"
            "  check_exit_code_zero\n"
            "  check_process_running\n"
            "  check_file_contains\n"
            "  check_directory_not_empty\n"
            "  check_port_open\n"
            "  check_output_contains\n"
            "  none\n\n"
            "Path rules:\n"
            "PATH RESOLUTION RULES — follow these strictly:\n\n"
            "1. Never generate bare relative paths like \"output\", \"testapp\",\n"
            "   \"documents\", \"downloads\". These are meaningless without an\n"
            "   anchor and will resolve to the wrong location.\n\n"
            "2. Every path in every step must be absolute.\n\n"
            "3. For well-known user directories, always use absolute\n"
            "   paths provided in user message context above:\n"
            "      'desktop'   -> use the Desktop absolute path provided\n"
            "      'documents' -> use the Documents absolute path provided\n"
            "      'downloads' -> use the Downloads absolute path provided\n"
            "      'pictures'  -> use the Pictures absolute path provided\n"
            "      'videos'    -> use the Videos absolute path provided\n"
            "      'music'     -> use the Music absolute path provided\n\n"
            "4. For nested paths user describes, compose them from\n"
            "   known absolute base. Examples:\n"
            "      \"documents folder in downloads\" ->\n"
            "        {Downloads absolute path}/Documents\n"
            "      \"output folder in documents\" ->\n"
            "        {Documents absolute path}/output\n"
            "      \"projects folder on desktop\" ->\n"
            "        {Desktop absolute path}/projects\n"
            "      \"testapp in downloads/projects\" ->\n"
            "        {Downloads absolute path}/projects/testapp\n"
            "      \"config folder in AppData\" ->\n"
            "        {AppData absolute path}/config\n\n"
            "5. If user mentions a folder path that is not one of the\n"
            "   well-known directories and gives no explicit location,\n"
            "   default to placing it under the user's home directory:\n"
            "      \"a folder called myfolder\" ->\n"
            "        {Home absolute path}/myfolder\n\n"
            "6. If user gives an explicit absolute path, use it exactly\n"
            "   as given without modification.\n\n"
            "7. For working_dir params in CLI steps, always use the same\n"
            "   absolute path resolution rules — never pass a bare name\n"
            "   like \"testapp\" as working_dir.\n\n"
            "8. Always use forward slashes in all generated paths even on\n"
            "   Windows — the execution layer handles conversion.\n\n"
            "CONTEXT RESOLUTION RULES:\n\n"
            "The user message includes a MEMORY CONTEXT section\n"
            "containing \"Last executed paths\". This shows the\n"
            "absolute paths used in recent successful executions.\n\n"
            "If the goal contains any of these pronoun references:\n"
            "  \"in it\", \"inside it\", \"in there\", \"in that folder\",\n"
            "  \"in that directory\", \"in the project\", \"in the repo\",\n"
            "  \"in the venv\", \"in the environment\", \"there\",\n"
            "  \"that folder\", \"that directory\", \"the same place\"\n\n"
            "You MUST resolve them using the Last executed paths\n"
            "section of the MEMORY CONTEXT as follows:\n\n"
            "1. Read every entry in \"Last executed paths\"\n"
            "2. Find the most recently executed path that is\n"
            "   semantically relevant to the pronoun in context\n"
            "   - \"in it\" after creating a folder → use that\n"
            "     folder's absolute path as the base directory\n"
            "   - \"in the venv\" → use the venv path\n"
            "   - \"in the project\" → use the project directory\n"
            "3. Substitute the resolved absolute path into the\n"
            "   step params — never use a bare pronoun in any\n"
            "   path parameter\n"
            "4. If multiple candidates exist, prefer the most\n"
            "   recent one\n"
            "5. If no candidate exists in memory context, use\n"
            "   Path.home() as the base and note the assumption\n"
            "   in the step description\n\n"
            "CRITICAL: A path parameter containing \"it\", \"there\",\n"
            "or any unresolved pronoun is always wrong. Every\n"
            "path in every step must be a fully qualified\n"
            "absolute path.\n\n"
            "CODE AWARENESS RULES:\n\n"
            "Before editing any existing file, always include a\n"
            "read_file or analyze_structure step first with\n"
            "depends_on pointing to it from the edit step.\n"
            "Never edit a file blindly without reading it first.\n\n"
            "When a goal involves modifying existing code:\n"
            "1. Step 1: read_file or analyze_structure to\n"
            "   understand current state\n"
            "2. Step 2+: edit_file, append_to_file, or\n"
            "   insert_after_line with depends_on: [1]\n\n"
            "For edit_file steps, the old_content param must be\n"
            "a realistic excerpt from the file. Since Gemini\n"
            "cannot know the exact content in advance, use a\n"
            "descriptive placeholder like:\n"
            "  \"<<READ_FIRST: use content from step 1 output>>\"\n"
            "The orchestrator will handle this via the\n"
            "code_edit_resolver (see below).\n\n"
            "When a CODE CONTEXT section is present in this\n"
            "message, use it to inform all planning decisions:\n"
            "- Use the exact file paths shown in the project\n"
            "  structure, never invent paths\n"
            "- Reference class names, function names, and\n"
            "  imports shown in the structure analysis\n"
            "- If a relevant file is listed in key files,\n"
            "  prefer editing it over creating a new file\n\n"
            "Ordering and dependencies:\n"
            "- Steps must be ordered so dependencies always come first.\n"
            "- depends_on must only reference earlier step IDs.\n"
            "- If no dependencies, depends_on must be [].\n\n"
            "Layer selection:\n"
            "- filesystem operations -> preferred_layer: os_api\n"
            "- run_command -> preferred_layer: cli\n"
            "- open_app/close_app/focus_app -> preferred_layer: app_adapter\n"
            "- system operations -> preferred_layer: os_api\n"
            "- code operations -> preferred_layer: os_api\n\n"
            "Fallback strategy:\n"
            "- If a CLI step could alternatively be done via filesystem, set fallback_strategy to \"use_filesystem\".\n"
            "- If a step is optional and failure should not block the task, set fallback_strategy to \"skip_optional\".\n"
            "- If no fallback exists, set fallback_strategy to null.\n\n"
            "Respond with raw JSON only. No markdown. No code fences. No explanations.\n"
            "No text before or after the JSON. The response must parse with json.loads directly.\n"
            "Use exactly this schema:\n"
            "{\n"
            '  "steps": [\n'
            "    {\n"
            '      "id": 1,\n'
            '      "description": "...",\n'
            '      "step_type": "...",\n'
            '      "preferred_layer": "...",\n'
            '      "operation": "...",\n'
            '      "params": {},\n'
            '      "expected_outcome": "...",\n'
            '      "verification_method": "...",\n'
            '      "depends_on": [],\n'
            '      "fallback_strategy": null\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )
