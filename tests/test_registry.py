from alara.mcp.registry import MCPRegistry

MOCK_TOOLS = [
    {"name": "GMAIL_FETCH_EMAILS", "description": "Fetch emails from inbox", "toolkit": "gmail", "inputSchema": {}},
    {"name": "GMAIL_SEND_EMAIL", "description": "Send an email", "toolkit": "gmail", "inputSchema": {}},
    {"name": "SLACK_SENDS_A_MESSAGE", "description": "Send a Slack message", "toolkit": "slack", "inputSchema": {}},
]

def test_load_groups_by_toolkit():
    r = MCPRegistry()
    r.load(MOCK_TOOLS)
    assert "gmail" in r.available_toolkits()
    assert "slack" in r.available_toolkits()

def test_find_tool_respects_active_toolkits():
    r = MCPRegistry()
    r.load(MOCK_TOOLS)
    # gmail active — should find it
    result = r.find_tool("comms_list", "show my inbox", ["gmail"])
    assert result == "GMAIL_FETCH_EMAILS"
    # slack not active — should not return slack tool
    result = r.find_tool("comms_send", "send a slack message", ["gmail"])
    assert result is None

def test_system_prompt_fragment_only_includes_active():
    r = MCPRegistry()
    r.load(MOCK_TOOLS)
    fragment = r.get_system_prompt_fragment(["gmail"])
    assert "GMAIL_FETCH_EMAILS" in fragment
    assert "SLACK" not in fragment

def test_system_prompt_fragment_empty_when_no_active():
    r = MCPRegistry()
    r.load(MOCK_TOOLS)
    assert r.get_system_prompt_fragment([]) == ""
