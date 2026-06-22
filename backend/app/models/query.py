import uuid
from pydantic import BaseModel, field_validator


class QueryRequest(BaseModel):
    chat_id: uuid.UUID
    question: str

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be empty")
        if len(v) > 1000:
            raise ValueError("question must not exceed 1000 characters")
        return v
