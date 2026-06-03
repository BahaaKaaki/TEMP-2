"""
Message domain entity.
"""
from dataclasses import dataclass
from typing import Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage


@dataclass
class Message:
    """Chat message domain entity."""
    
    id: str
    role: str
    content: str
    timestamp: str
    additional_data: Optional[dict] = None
    
    def is_user_message(self) -> bool:
        """Check if message is from user."""
        return self.role == "user"
    
    def is_assistant_message(self) -> bool:
        """Check if message is from assistant."""
        return self.role == "assistant"
    
    def is_empty(self) -> bool:
        """Check if message content is empty."""
        return not self.content or self.content.strip() == ""
    
    def to_langchain_message(self) -> BaseMessage:
        """Convert to LangChain message format."""
        kwargs = {"additional_kwargs": self.additional_data or {}}
        
        if self.role == "user":
            return HumanMessage(content=self.content, **kwargs)
        elif self.role == "assistant":
            return AIMessage(content=self.content, **kwargs)
        else:
            return SystemMessage(content=self.content, **kwargs)
    
    @classmethod
    def from_langchain_message(cls, msg: BaseMessage, msg_id: str = None) -> "Message":
        """Create from LangChain message."""
        role = "user" if msg.__class__.__name__ == "HumanMessage" else "assistant"
        
        additional_kwargs = getattr(msg, "additional_kwargs", {})
        message_id = msg_id or additional_kwargs.get("message_id", "")
        
        return cls(
            id=message_id,
            role=role,
            content=msg.content,
            timestamp=additional_kwargs.get("timestamp", ""),
            additional_data=additional_kwargs
        )

