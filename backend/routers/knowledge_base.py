"""Knowledge base API endpoints: PDF documents, Q&A pairs, AI settings."""

import logging
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from models.knowledge_base import (
    UploadDocumentResponse, ListDocumentsResponse, DocumentSummary,
    QAPairCreate, QAPairUpdate, QAPairResponse, ListQAPairsResponse,
    AISettingsRequest, AISettingsResponse,
)
from services.kb_service import KBService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge-base", tags=["knowledge-base"])

MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024  # 10MB


@router.post("/documents", response_model=UploadDocumentResponse, status_code=202)
async def upload_document(request: Request, file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Only PDF files are supported")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_PDF_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10MB limit")

    tenant_id = request.state.tenant_id
    result = await KBService.upload_document(tenant_id, file.filename, file_bytes)
    return UploadDocumentResponse(**result)


@router.get("/documents", response_model=ListDocumentsResponse)
async def list_documents(request: Request):
    tenant_id = request.state.tenant_id
    documents = await KBService.list_documents(tenant_id)
    return ListDocumentsResponse(documents=[DocumentSummary(**d) for d in documents])


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(request: Request, document_id: str):
    tenant_id = request.state.tenant_id
    deleted = await KBService.delete_document(tenant_id, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")


@router.post("/qa-pairs", response_model=QAPairResponse, status_code=201)
async def create_qa_pair(request: Request, req: QAPairCreate):
    tenant_id = request.state.tenant_id
    result = await KBService.create_qa_pair(tenant_id, req.question, req.answer)
    return QAPairResponse(**result)


@router.get("/qa-pairs", response_model=ListQAPairsResponse)
async def list_qa_pairs(request: Request):
    tenant_id = request.state.tenant_id
    qa_pairs = await KBService.list_qa_pairs(tenant_id)
    return ListQAPairsResponse(qa_pairs=[QAPairResponse(**qa) for qa in qa_pairs])


@router.patch("/qa-pairs/{qa_id}", response_model=QAPairResponse)
async def update_qa_pair(request: Request, qa_id: str, req: QAPairUpdate):
    tenant_id = request.state.tenant_id
    result = await KBService.update_qa_pair(tenant_id, qa_id, req.question, req.answer)
    if not result:
        raise HTTPException(status_code=404, detail="Q&A pair not found")
    return QAPairResponse(**result)


@router.delete("/qa-pairs/{qa_id}", status_code=204)
async def delete_qa_pair(request: Request, qa_id: str):
    tenant_id = request.state.tenant_id
    deleted = await KBService.delete_qa_pair(tenant_id, qa_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Q&A pair not found")


@router.get("/ai-settings", response_model=AISettingsResponse)
async def get_ai_settings(request: Request):
    tenant_id = request.state.tenant_id
    ai_enabled = await KBService.get_ai_enabled(tenant_id)
    return AISettingsResponse(ai_enabled=ai_enabled)


@router.patch("/ai-settings", response_model=AISettingsResponse)
async def update_ai_settings(request: Request, req: AISettingsRequest):
    tenant_id = request.state.tenant_id
    ai_enabled = await KBService.set_ai_enabled(tenant_id, req.ai_enabled)
    return AISettingsResponse(ai_enabled=ai_enabled)
