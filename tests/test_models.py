import pytest
from pydantic import ValidationError
from src.models import ChatCompletionRequest, Message

def test_chat_completion_request_valid():
    request = ChatCompletionRequest(
        model="claude-3-opus",
        messages=[{"role": "user", "content": "Hello"}]
    )
    assert request.model == "claude-3-opus"
    assert len(request.messages) == 1
    assert request.stream is False  # Default

def test_chat_completion_request_invalid_empty_messages():
    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="claude-3-opus",
            messages=[]
        )

def test_message_role_enum():
    with pytest.raises(ValidationError):
        Message(role="invalid", content="hi")
