import time
import uuid
from typing import List, Optional, Literal, Union
from pydantic import BaseModel, Field, field_validator

class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

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
