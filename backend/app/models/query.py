import uuid
from pydantic import BaseModel, field_validator


class QueryRequest(BaseModel):
    document_ids: list[uuid.UUID]
    question: str

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if not v:
            raise ValueError("document_ids must not be empty")
        if len(v) > 10:
            raise ValueError("Cannot query more than 10 documents at once")
        return v

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question must not be empty")
        if len(v) > 1000:
            raise ValueError("question must not exceed 1000 characters")
        return v
