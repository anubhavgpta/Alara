from composio import Composio
from google import genai
from google.genai import types
from loguru import logger
import json

# Import CapabilityResult from filesystem
from capabilities.filesystem import (
    CapabilityResult
)

# Fallback tools if auto-discovery fails
# Maps toolkit slug to list of tool names
FALLBACK_TOOLS = {
    "gmail": [
        "GMAIL_CREATE_EMAIL_DRAFT",
        "GMAIL_SEND_EMAIL",  # Now available with the fix!
        "GMAIL_SEND_DRAFT",  # Also available
        "GMAIL_FETCH_EMAILS",
        "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
        "GMAIL_REPLY_TO_THREAD",
        "GMAIL_FORWARD_MESSAGE",
        "GMAIL_DELETE_MESSAGE",
        "GMAIL_GET_PROFILE",
        "GMAIL_CREATE_LABEL",
        "GMAIL_DELETE_LABEL",
        "GMAIL_GET_LABEL",
        "GMAIL_UPDATE_LABEL",
        "GMAIL_PATCH_LABEL",
        "GMAIL_LIST_LABELS",
        "GMAIL_CREATE_FILTER",
        "GMAIL_DELETE_FILTER",
        "GMAIL_GET_FILTER",
        "GMAIL_LIST_FILTERS",
        "GMAIL_GET_DRAFT",
        "GMAIL_DELETE_DRAFT",
        "GMAIL_UPDATE_DRAFT",
        "GMAIL_LIST_DRAFTS",
        "GMAIL_GET_ATTACHMENT",
        "GMAIL_IMPORT_MESSAGE",
        "GMAIL_INSERT_MESSAGE",
        "GMAIL_BATCH_DELETE_MESSAGES",
        "GMAIL_BATCH_MODIFY_MESSAGES",
        "GMAIL_ADD_LABEL_TO_EMAIL",
        "GMAIL_DELETE_THREAD",
        "GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
        "GMAIL_LIST_MESSAGES",
        "GMAIL_LIST_THREADS",
        "GMAIL_MODIFY_THREAD_LABELS",
        "GMAIL_MOVE_TO_TRASH",
        "GMAIL_TRASH_THREAD",
        "GMAIL_UNTRASH_MESSAGE",
        "GMAIL_UNTRASH_THREAD",
        "GMAIL_SEARCH_PEOPLE",
        "GMAIL_GET_PEOPLE",
        "GMAIL_GET_AUTO_FORWARDING",
        "GMAIL_LIST_FORWARDING_ADDRESSES",
        "GMAIL_LIST_HISTORY",
        "GMAIL_STOP_WATCH",
        "GMAIL_GET_LANGUAGE_SETTINGS",
        "GMAIL_UPDATE_LANGUAGE_SETTINGS",
        "GMAIL_GET_VACATION_SETTINGS",
        "GMAIL_UPDATE_VACATION_SETTINGS",
        "GMAIL_SETTINGS_GET_IMAP",
        "GMAIL_SETTINGS_GET_POP",
        "GMAIL_UPDATE_IMAP_SETTINGS",
        "GMAIL_UPDATE_POP",
        "GMAIL_LIST_SEND_AS",
        "GMAIL_PATCH_SEND_AS",
        "GMAIL_SETTINGS_SEND_AS_GET",
        "GMAIL_UPDATE_SEND_AS",
        "GMAIL_LIST_CSE_IDENTITIES",
        "GMAIL_LIST_CSE_KEYPAIRS",
        "GMAIL_LIST_SMIME_INFO",
    ],
    "slack": [
        "SLACK_SENDS_A_MESSAGE",
        "SLACK_LIST_ALL_SLACK_TEAM_CHANNELS",
        "SLACK_FETCH_CONVERSATION_HISTORY",
    ],
    "googlecalendar": [
        "GOOGLECALENDAR_CREATE_EVENT",
        "GOOGLECALENDAR_LIST_EVENTS",
        "GOOGLECALENDAR_DELETE_EVENT",
        "GOOGLECALENDAR_UPDATE_EVENT",
    ],
    "notion": [
        "NOTION_CREATE_A_PAGE",
        "NOTION_FETCH_PAGE",
        "NOTION_SEARCH_NOTION_PAGE",
    ],
}

# Schema cleaning — required for Gemini
TYPE_MAP = {
    "string":  "STRING",
    "number":  "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array":   "ARRAY",
    "object":  "OBJECT",
}

FORBIDDEN_KEYS = {
    "title",
    "examples",
    "minimum",
    "maximum",
    "default",
    "human_parameter_name",
    "human_parameter_description",
    "minLength",
    "maxLength",
    "file_uploadable",
    "human_readable_description",
    "display_name",
    "additional_properties",
    "additionalProperties",  # Handle camelCase version
    "x-",
}

def clean_schema(schema: dict) -> dict:
    """
    Recursively clean a Composio tool schema
    to be compatible with Gemini's
    FunctionDeclaration pydantic validator.

    Rules:
    1. Remove all forbidden keys
    2. Uppercase all type values
    3. Recurse into properties and items
    4. Remove any key starting with 'x-'
    """
    if not isinstance(schema, dict):
        return schema

    cleaned = {}
    for k, v in schema.items():
        # Skip forbidden keys entirely
        if k in FORBIDDEN_KEYS:
            continue
        # Skip any key starting with 'x-'
        if isinstance(k, str) and k.startswith("x-"):
            continue

        if k == "type" and isinstance(v, str):
            # Uppercase type value
            cleaned[k] = TYPE_MAP.get(v, v.upper())

        elif k == "properties" and isinstance(v, dict):
            # Recurse into each property
            cleaned[k] = {
                pk: clean_schema(pv)
                for pk, pv in v.items()
            }

        elif k == "items" and isinstance(v, dict):
            # Recurse into array items
            cleaned[k] = clean_schema(v)

        elif k == "anyOf" and isinstance(v, list):
            # Recurse into anyOf schemas
            cleaned[k] = [
                clean_schema(s)
                if isinstance(s, dict) else s
                for s in v
            ]

        elif k == "allOf" and isinstance(v, list):
            # Recurse into allOf schemas
            cleaned[k] = [
                clean_schema(s)
                if isinstance(s, dict) else s
                for s in v
            ]

        elif isinstance(v, dict):
            # Recurse into any other dict value
            cleaned[k] = clean_schema(v)

        elif isinstance(v, list):
            # Recurse into list items if dicts
            cleaned[k] = [
                clean_schema(i)
                if isinstance(i, dict) else i
                for i in v
            ]

        else:
            cleaned[k] = v

    return cleaned

class ComposioCapability:

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.api_key = self.config.get(
            "composio_api_key", ""
        )
        self.user_id = self.config.get(
            "composio_user_id", ""
        )
        self.gemini_api_key = self.config.get(
            "api_key", ""
        )
        self.model = self.config.get(
            "model", "gemini-2.5-flash"
        )
        self.services = self.config.get(
            "composio_services", []
        )
        
        # Cache for discovered toolkits and tools
        self._cached_slugs = None
        self._cached_tools = None

    def execute(
        self,
        operation: str,
        params: dict
    ) -> CapabilityResult:

        if not self.api_key:
            return CapabilityResult(
                success=False,
                error=(
                    "Composio not configured. "
                    "Run alara-setup to add "
                    "your Composio API key."
                )
            )

        if not self.user_id:
            return CapabilityResult(
                success=False,
                error=(
                    "Composio user ID not set. "
                    "Run alara-setup to set "
                    "your Composio user ID."
                )
            )

        try:
            return self._run_agentic_loop(
                operation, params
            )
        except Exception as e:
            logger.error(
                f"Composio error: {e}"
            )
            logger.error(
                f"Error type: {type(e).__name__}"
            )
            logger.error(
                f"Error details: {str(e)}"
            )
            return CapabilityResult(
                success=False,
                error=str(e)
            )

    def _discover_connected_toolkits(
        self,
        composio: "Composio"
    ) -> list[str]:
        """
        Query Composio for all active connected
        accounts for this user. Returns list of
        toolkit slugs e.g. ['gmail', 'slack'].
        """
        try:
            accounts = \
                composio.connected_accounts.list()
            items = getattr(accounts, 'items', [])
            slugs = []
            for account in items:
                toolkit = getattr(
                    account, 'toolkit', None
                )
                slug = getattr(
                    toolkit, 'slug', ''
                ) if toolkit else ''
                status = getattr(
                    account, 'status', ''
                )
                if slug and status == 'ACTIVE':
                    slugs.append(slug)
            # Remove duplicates while preserving order
            seen = set()
            unique_slugs = []
            for slug in slugs:
                if slug not in seen:
                    seen.add(slug)
                    unique_slugs.append(slug)
            logger.info(
                f"Composio: discovered connected "
                f"toolkits: {unique_slugs}"
            )
            return unique_slugs
        except Exception as e:
            logger.warning(
                f"Composio: toolkit discovery "
                f"failed: {e}"
            )
            return []

    def _get_all_tools(
        self,
        composio: "Composio",
        slugs: list[str]
    ) -> list:
        """
        Fetch all tool definitions for the given
        toolkit slugs. Falls back to hardcoded
        FALLBACK_TOOLS if needed.
        First tries fetching by toolkit slug
        directly, falls back to named tool list.
        """
        all_tools = []
        seen_tools = set()  # Track tool names to avoid duplicates

        for slug in slugs:
            try:
                # Try fetching by toolkit
                tools = composio.tools.get(
                    user_id=self.user_id,
                    toolkits=[slug],
                    limit=1000  # Use high limit to get all tools (default is 20)
                )
                logger.debug(
                    f"Composio: raw tools from {slug}: {len(tools) if tools else 0}"
                )
                if tools:
                    tools_added = 0
                    for tool in tools:
                        tool_name = tool.get("function", {}).get("name", "")
                        logger.debug(
                            f"Composio: processing tool: {tool_name}"
                        )
                        if tool_name and tool_name not in seen_tools:
                            all_tools.append(tool)
                            seen_tools.add(tool_name)
                            tools_added += 1
                    logger.info(
                        f"Composio: loaded "
                        f"{tools_added} unique tools "
                        f"from {slug}"
                    )
                    continue
            except Exception:
                pass

            # Fallback to named tool list
            named = FALLBACK_TOOLS.get(slug, [])
            logger.debug(
                f"Composio: fallback tools for {slug}: {named}"
            )
            if named:
                try:
                    tools = composio.tools.get(
                        user_id=self.user_id,
                        tools=named,
                        limit=1000  # Use high limit to get all tools (default is 20)
                    )
                    logger.debug(
                        f"Composio: raw fallback tools from {slug}: {len(tools) if tools else 0}"
                    )
                    if tools:
                        tools_added = 0
                        for tool in tools:
                            tool_name = tool.get("function", {}).get("name", "")
                            logger.debug(
                                f"Composio: processing fallback tool: {tool_name}"
                            )
                            if tool_name and tool_name not in seen_tools:
                                all_tools.append(tool)
                                seen_tools.add(tool_name)
                                tools_added += 1
                        logger.info(
                            f"Composio: loaded "
                            f"{tools_added} unique tools "
                            f"from {slug} "
                            f"(fallback)"
                        )
                except Exception as e:
                    logger.warning(
                        f"Composio: failed to "
                        f"load {slug} tools: {e}"
                    )

        logger.debug(
            f"Composio: returning {len(all_tools)} total tools"
        )
        return all_tools

    def discover_and_cache(self) -> list[str]:
        """
        Public method called at startup to
        discover connected services and cache
        them. Returns list of connected toolkit
        slugs for display on home screen.
        Called once per session from main.py.
        """
        if self._cached_slugs is not None:
            return self._cached_slugs

        composio = Composio(api_key=self.api_key)
        slugs = self._discover_connected_toolkits(
            composio
        )
        self._cached_slugs = slugs
        return slugs

    def _build_goal_prompt(
        self,
        operation: str,
        params: dict
    ) -> str:
        """
        Build a natural language goal for
        Gemini from operation + params.
        """
        op_prompts = {
            "send_email": (
                "Send an email to {to} with subject '{subject}' and body '{body}'. "
                "Use GMAIL_SEND_EMAIL to send directly, or GMAIL_CREATE_EMAIL_DRAFT as fallback. "
                "You have access to Gmail tools including GMAIL_SEND_EMAIL."
            ),
            "read_emails": (
                "Fetch the last {count} emails "
                "from my Gmail inbox"
            ),
            "create_calendar_event": (
                "Create a calendar event titled "
                "'{title}' on {date} at {time}"
            ),
            "get_calendar_events": (
                "List my upcoming calendar events"
            ),
            "send_slack_message": (
                "Send a Slack message to "
                "channel {channel}: {message}"
            ),
            "create_notion_page": (
                "Create a Notion page titled "
                "'{title}' with content: {content}"
            ),
        }

        template = op_prompts.get(
            operation,
            f"Perform the following action: "
            f"{operation} with params: {params}"
        )

        try:
            return template.format(**params)
        except KeyError:
            return (
                f"Perform: {operation} "
                f"with {params}"
            )

    def _run_agentic_loop(
        self,
        operation: str,
        params: dict
    ) -> CapabilityResult:
        """
        Agentic loop: Gemini decides which
        Composio tools to call and in what
        order until the task is complete.
        """
        composio = Composio(
            api_key=self.api_key
        )
        client = genai.Client(
            api_key=self.gemini_api_key
        )

        # Discover toolkits if not cached
        if self._cached_slugs is None:
            self._cached_slugs = \
                self._discover_connected_toolkits(
                    composio
                )

        # Fetch tools if not cached
        if self._cached_tools is None:
            self._cached_tools = self._get_all_tools(
                composio,
                self._cached_slugs
            )

        composio_tools = self._cached_tools
        
        # Filter tools based on operation to avoid overwhelming Gemini
        operation_tool_map = {
            "send_email": ["GMAIL_SEND_EMAIL", "GMAIL_CREATE_EMAIL_DRAFT"],  # Include both tools
            "read_emails": ["GMAIL_FETCH_EMAILS", "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"],
            "create_calendar_event": ["GOOGLECALENDAR_CREATE_EVENT"],
            "get_calendar_events": ["GOOGLECALENDAR_LIST_EVENTS"],
            "send_slack_message": ["SLACK_SENDS_A_MESSAGE"],
            "create_notion_page": ["NOTION_CREATE_A_PAGE"],
        }
        
        relevant_tools = operation_tool_map.get(operation, [])
        if relevant_tools:
            # Filter to only relevant tools
            filtered_tools = [
                tool for tool in composio_tools 
                if tool.get('function', {}).get('name') in relevant_tools
            ]
            if filtered_tools:
                composio_tools = filtered_tools
                logger.info(
                    f"Composio: filtered to {len(composio_tools)} relevant tools for {operation}"
                )

        if not composio_tools:
            return CapabilityResult(
                success=False,
                error=(
                    "No connected tools found. "
                    "Visit composio.dev to connect "
                    "Gmail, Slack, or other services."
                )
            )

        logger.info(
            f"Composio: passing "
            f"{len(composio_tools)} tools to Gemini"
        )
        logger.debug(
            f"Composio: tool names: "
            f"{[t.get('function', {}).get('name', 'unknown') for t in composio_tools]}"
        )

        # Build Gemini tool declarations
        gemini_tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=tool["function"]["name"],
                        description=tool["function"]
                            ["description"],
                        parameters=clean_schema(
                            tool["function"]
                            ["parameters"]
                        )
                    )
                    for tool in composio_tools
                ]
            )
        ]
        
        # Debug: Print the first few function declarations
        if composio_tools:
            logger.debug(
                f"Composio: sample function declaration: "
                f"{gemini_tools[0].function_declarations[0].name}"
            )
            logger.debug(
                f"Composio: sample parameters: "
                f"{gemini_tools[0].function_declarations[0].parameters}"
            )
        
        # Debug: Print the tools config
        logger.debug(
            f"Composio: tools config length: {len(gemini_tools)}"
        )
        if gemini_tools and gemini_tools[0].function_declarations:
            logger.debug(
                f"Composio: first tool declaration count: {len(gemini_tools[0].function_declarations)}"
            )
            # Check if GMAIL_CREATE_EMAIL_DRAFT is in the declarations
            gmail_draft_found = any(
                fd.name == "GMAIL_CREATE_EMAIL_DRAFT" 
                for fd in gemini_tools[0].function_declarations
            )
            logger.debug(
                f"Composio: GMAIL_CREATE_EMAIL_DRAFT found in declarations: {gmail_draft_found}"
            )

        # Build goal prompt
        goal = self._build_goal_prompt(
            operation, params
        )
        logger.info(
            f"Composio agentic loop: {goal}"
        )

        # Run agentic loop
        messages = [{
            "role": "user",
            "parts": [{"text": goal}]
        }]
        
        logger.debug(
            f"Composio: starting agentic loop with goal: {goal}"
        )
        logger.debug(
            f"Composio: initial messages: {messages}"
        )

        max_iterations = 5
        iteration = 0
        final_output = ""

        while iteration < max_iterations:
            iteration += 1

            response = client.models\
                .generate_content(
                    model=self.model,
                    contents=messages,
                    config=types\
                        .GenerateContentConfig(
                            tools=gemini_tools
                        )
                )
            
            logger.debug(
                f"Composio: Gemini response received, iteration {iteration}"
            )
            logger.debug(
                f"Composio: response candidates: {len(response.candidates) if response.candidates else 0}"
            )

            candidate = response.candidates[0]
            parts = candidate.content.parts or []
            function_calls = [
                p for p in parts
                if p.function_call and
                   p.function_call.name
            ]
            
            logger.debug(
                f"Composio: found {len(function_calls)} function calls in iteration {iteration}"
            )
            for fc in function_calls:
                logger.debug(
                    f"Composio: function call: {fc.function_call.name} with args: {dict(fc.function_call.args)}"
                )

            if function_calls:
                logger.info(
                    f"Composio: executing {len(function_calls)} function calls in iteration {iteration}"
                )
                # Add model response to history
                messages.append({
                    "role": "model",
                    "parts": [
                        {"function_call":
                             p.function_call}
                        if p.function_call and
                           p.function_call.name
                        else {"text": p.text}
                        for p in parts
                    ]
                })

                # Execute each tool call
                tool_results = []
                for part in function_calls:
                    fc = part.function_call
                    tool_name = fc.name
                    tool_args = dict(fc.args)

                    logger.info(
                        f"Composio: calling "
                        f"{tool_name} with "
                        f"{tool_args}"
                    )

                    try:
                        result = \
                            composio.tools.execute(
                                tool_name,
                                user_id=self.user_id,
                                arguments=tool_args,
                                dangerously_skip_version_check=True
                            )
                        
                        logger.info(
                            f"Composio: {tool_name} result: "
                            f"{str(result)[:200]}"
                        )
                        tool_results.append({
                            "function_response": {
                                "name": tool_name,
                                "response": {
                                    "result":
                                        json.dumps(
                                            result
                                        )
                                }
                            }
                        })
                    except Exception as e:
                        logger.error(
                            f"Tool {tool_name} "
                            f"failed: {e}"
                        )
                        tool_results.append({
                            "function_response": {
                                "name": tool_name,
                                "response": {
                                    "result":
                                        f"Error: {e}"
                                }
                            }
                        })

                messages.append({
                    "role": "user",
                    "parts": tool_results
                })

            else:
                # No more tool calls — done
                text_parts = [
                    p.text for p in parts
                    if hasattr(p, 'text')
                       and p.text
                ]
                final_output = " ".join(
                    text_parts
                )
                logger.debug(
                    f"Composio: no function calls, final text output: {final_output[:200]}"
                )
                break

        if not final_output:
            final_output = (
                "Task completed via Composio."
            )

        return CapabilityResult(
            success=True,
            output=final_output
        )
