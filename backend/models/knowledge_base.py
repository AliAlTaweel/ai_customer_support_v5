"""Request/response models for the knowledge base API."""

from pydantic import BaseModel, Field
from typing import Optional, List


class DocumentSummary(BaseModel):
    document_id: str
    filename: str
    status: str  # "processing" | "ready" | "failed"
    chunk_count: int
    uploaded_at: str


class UploadDocumentResponse(BaseModel):
    document_id: str
    filename: str
    status: str


class ListDocumentsResponse(BaseModel):
    documents: List[DocumentSummary]


class QAPairCreate(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    answer: str = Field(..., min_length=1, max_length=5000)


class QAPairUpdate(BaseModel):
    question: Optional[str] = Field(None, min_length=1, max_length=1000)
    answer: Optional[str] = Field(None, min_length=1, max_length=5000)


class QAPairResponse(BaseModel):
    qa_id: str
    question: str
    answer: str
    updated_at: str


class ListQAPairsResponse(BaseModel):
    qa_pairs: List[QAPairResponse]


class AISettingsRequest(BaseModel):
    ai_enabled: bool


class AISettingsResponse(BaseModel):
    ai_enabled: bool
