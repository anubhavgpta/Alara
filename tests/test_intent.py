from alara.core.intent import IntentParser

parser = IntentParser()

def test_comms_intents():
    assert parser.classify("show me my inbox") == "comms_list"
    assert parser.classify("read the email from Sarah") == "comms_read"
    assert parser.classify("send an email to dan@example.com") == "comms_send"
    assert parser.classify("search emails about invoice") == "comms_search"

def test_calendar_intents():
    assert parser.classify("what meetings do I have tomorrow") == "calendar_list"
    assert parser.classify("schedule a call with Priya on Friday") == "calendar_create"

def test_task_intents():
    assert parser.classify("show my open GitHub issues") == "task_list"
    assert parser.classify("create a Linear ticket for the login bug") == "task_create"

def test_l0_intents_unchanged():
    assert parser.classify("research quantum computing") == "research"
    assert parser.classify("list files in my workspace") == "file_list"
    assert parser.classify("hello how are you") == "chat"
