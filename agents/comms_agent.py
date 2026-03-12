from agents.base import BaseAgent

class CommsAgent(BaseAgent):

    name = "comms"
    description = (
        "Sends emails, reads inbox, manages "
        "calendar and Slack via Composio"
    )
    capabilities = ["comms", "filesystem"]

    system_prompt = """
You are the Comms Agent for ALARA.
You specialize in communication and messaging
powered by Composio and Gemini.

Your strengths:
- Sending and reading emails via Gmail
- Sending Slack messages to channels
- Creating and reading Google Calendar events
- Creating tasks and pages in Notion
- Summarizing email threads and inboxes

When planning:
- Use send_email for all email sending tasks
- Use read_emails to fetch inbox content
- Use send_slack_message for Slack
- Use create_calendar_event for scheduling
- Use create_notion_page for notes and tasks
- Always confirm the result in the final step

You have access to: Composio integrations
powered by Gemini function calling
    """

    def can_handle(
        self, goal: str, scope: str
    ) -> bool:
        keywords = [
            "email", "gmail", "send message",
            "slack", "whatsapp", "notify",
            "calendar", "schedule", "meeting",
            "invite", "notion", "task",
            "composio", "webhook", "message me",
            "remind me", "set a reminder",
            "discord", "linear", "trello",
            "send a notification", "dm me",
            "check my email", "read my email",
            "inbox", "draft", "reply to",
        ]
        goal_lower = goal.lower()
        return any(
            k in goal_lower for k in keywords
        )
