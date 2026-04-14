from alara.core.errors import (
    AlaraError, AlaraAPIError, AlaraMCPError,
    AlaraPermissionError, AlaraConfigError
)

def test_error_hierarchy():
    assert issubclass(AlaraAPIError, AlaraError)
    assert issubclass(AlaraMCPError, AlaraError)
    assert issubclass(AlaraPermissionError, AlaraError)
    assert issubclass(AlaraConfigError, AlaraError)

def test_mcp_error_carries_message():
    e = AlaraMCPError("tool call failed")
    assert "tool call failed" in str(e)
