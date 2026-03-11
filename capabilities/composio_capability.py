from composio import Composio
from google import genai
from google.genai import types
from loguru import logger
import json

# Import CapabilityResult from filesystem
from alara.capabilities.filesystem import (
    CapabilityResult
)

# Gmail tools to expose to Gemini
GMAIL_TOOLS = [
    "GMAIL_SEND_EMAIL",
    "GMAIL_FETCH_EMAILS",
    "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
    "GMAIL_REPLY_TO_THREAD",
    "GMAIL_CREATE_DRAFT",
    "GMAIL_DELETE_MESSAGE",
    "GMAIL_GET_PROFILE",
    "GMAIL_LIST_LABELS",
    "GMAIL_SEARCH_PEOPLE",
]

# Slack tools
SLACK_TOOLS = [
    "SLACK_SENDS_A_MESSAGE",
    "SLACK_LIST_ALL_SLACK_TEAM_CHANNELS",
    "SLACK_FETCH_CONVERSATION_HISTORY",
]

# Google Calendar tools
GCAL_TOOLS = [
    "GOOGLECALENDAR_CREATE_EVENT",
    "GOOGLECALENDAR_LIST_EVENTS",
    "GOOGLECALENDAR_GET_EVENT",
    "GOOGLECALENDAR_DELETE_EVENT",
    "GOOGLECALENDAR_UPDATE_EVENT",
]

# Notion tools
NOTION_TOOLS = [
    "NOTION_CREATE_A_PAGE",
    "NOTION_FETCH_PAGE",
    "NOTION_SEARCH_NOTION_PAGE",
    "NOTION_ADD_PAGE_CONTENT",
]

# Schema cleaning — required for Gemini
TYPE_MAP = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}

FORBIDDEN_KEYS = {
    "title", "examples", "minimum",
    "maximum", "default",
    "human_parameter_name",
    "human_parameter_description",
    "minLength", "maxLength"
}

# Additional keys to remove for Gmail tools to avoid attachment validation issues
GMAIL_FORBIDDEN_KEYS = {
    "file_uploadable", "attachment"
}

def clean_schema(schema: dict) -> dict:
    cleaned = {}
    for k, v in schema.items():
        if k in FORBIDDEN_KEYS:
            continue
        if k == "type":
            cleaned[k] = TYPE_MAP.get(v, v)
        elif k == "properties" and isinstance(v, dict):
            cleaned[k] = {
                pk: clean_schema(pv)
                for pk, pv in v.items()
            }
        elif k == "items" and isinstance(v, dict):
            cleaned[k] = clean_schema(v)
        else:
            cleaned[k] = v
    return cleaned

def clean_gmail_schema(schema: dict) -> dict:
    """Additional cleaning for Gmail tools to remove attachment-related properties."""
    cleaned = clean_schema(schema)
    
    # Remove attachment-related properties that cause validation errors
    if "properties" in cleaned:
        props = cleaned["properties"]
        # Remove attachment-related keys
        for key in list(props.keys()):
            if any(attachment_key in key.lower() for attachment_key in ["attachment", "uploadable", "file"]):
                del props[key]
        cleaned["properties"] = props
    
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

    def _get_tools_for_operation(
        self, operation: str
    ) -> list[str]:
        """
        Return the relevant tool list based
        on the operation type.
        """
        op = operation.lower()

        if any(x in op for x in [
            "email", "gmail", "mail",
            "inbox", "draft", "reply"
        ]):
            return GMAIL_TOOLS

        if "slack" in op:
            return SLACK_TOOLS

        if any(x in op for x in [
            "calendar", "event", "schedule",
            "meeting"
        ]):
            return GCAL_TOOLS

        if "notion" in op or "task" in op:
            return NOTION_TOOLS

        # Default: return all connected tools
        all_tools = []
        services = self.services
        if "gmail" in services:
            all_tools += GMAIL_TOOLS
        if "slack" in services:
            all_tools += SLACK_TOOLS
        if "google_calendar" in services:
            all_tools += GCAL_TOOLS
        if "notion" in services:
            all_tools += NOTION_TOOLS
        return all_tools or GMAIL_TOOLS

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
                "Send an email to {to} with "
                "subject '{subject}' and "
                "body: {body}"
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

        # Get relevant tools
        tool_names = \
            self._get_tools_for_operation(
                operation
            )

        # Fetch tool definitions from Composio
        try:
            composio_tools = composio.tools.get(
                user_id=self.user_id,
                tools=tool_names
            )
        except Exception as e:
            return CapabilityResult(
                success=False,
                error=f"Failed to load tools: {e}"
            )

        if not composio_tools:
            return CapabilityResult(
                success=False,
                error=(
                    "No Composio tools available. "
                    "Check your connected accounts "
                    "at composio.dev"
                )
            )

        # Build Gemini tool declarations
        gemini_tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=tool["function"]["name"],
                        description=tool["function"]
                            ["description"],
                        parameters=clean_gmail_schema(
                            tool["function"]
                            ["parameters"]
                        ) if "gmail" in tool["function"]["name"].lower()
                        else clean_schema(
                            tool["function"]
                            ["parameters"]
                        )
                    )
                    for tool in composio_tools
                ]
            )
        ]

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

            candidate = response.candidates[0]
            parts = candidate.content.parts or []
            function_calls = [
                p for p in parts
                if p.function_call and
                   p.function_call.name
            ]

            if function_calls:
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
                break

        if not final_output:
            final_output = (
                "Task completed via Composio."
            )

        return CapabilityResult(
            success=True,
            output=final_output
        )
