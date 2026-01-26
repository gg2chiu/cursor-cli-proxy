import time
import uuid
from typing import List, Optional, Literal, Union, Any
from pydantic import BaseModel, Field, field_validator

# Content part types for multimodal messages (OpenAI format)
class TextContentPart(BaseModel):
    type: Literal["text"]
    text: str

class ImageUrlDetail(BaseModel):
    url: str
    detail: Optional[str] = None

class ImageContentPart(BaseModel):
    type: Literal["image_url"]
    image_url: ImageUrlDetail

# Union of all content part types
ContentPart = Union[TextContentPart, ImageContentPart]

class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: Union[str, List[ContentPart]]
    
    def get_text_content(self) -> str:
        """Extract text content from message, handling both string and list formats."""
        if isinstance(self.content, str):
            return self.content
        # Extract text from content parts
        texts = []
        for part in self.content:
            if isinstance(part, TextContentPart) or (isinstance(part, dict) and part.get("type") == "text"):
                text = part.text if isinstance(part, TextContentPart) else part.get("text", "")
                texts.append(text)
            elif isinstance(part, ImageContentPart) or (isinstance(part, dict) and part.get("type") == "image_url"):
                texts.append("[Image]")
        return "\n".join(texts)

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    stream: bool = False
    
    @field_validator('messages')
    @classmethod
    def check_messages_not_empty(cls, v):
        if not v:
            raise ValueError('messages list must not be empty')
        return v

class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: Optional[str] = "stop"

class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4()}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[Choice]

class ChunkDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None

class ChunkChoice(BaseModel):
    index: int
    delta: ChunkDelta
    finish_reason: Optional[str] = None

class ChatCompletionChunk(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4()}")
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChunkChoice]

class Model(BaseModel):
    id: str
    object: str = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = "cursor"
    name: Optional[str] = None

class ModelList(BaseModel):
    object: str = "list"
    data: List[Model]
