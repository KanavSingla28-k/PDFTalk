import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus
from app.exceptions import (
    DocumentNotFoundError,
    DocumentNotReadyError,
)


async def validate_documents_for_query(
    document_ids: list[uuid.UUID],
    user_id: uuid.UUID,
    db: AsyncSession,
) -> list[Document]:
    """
    For each document_id in the request:
      - Must exist
      - Must be owned by the requesting user (returns 404 if not — never 403,
        to avoid leaking that the document exists at all)
      - Must be in READY status

    Returns the list of Document ORM objects on success.
    Raises DocumentNotFoundError or DocumentNotReadyError on failure.
    """
    result = await db.execute(
        select(Document).where(Document.id.in_(document_ids))
    )
    documents = result.scalars().all()

    # Build a lookup by id for O(1) access
    found = {doc.id: doc for doc in documents}

    for doc_id in document_ids:
        doc = found.get(doc_id)

        # Not found OR belongs to a different user → 404
        # The 404 (not 403) is intentional: a 403 would reveal the resource exists
        if doc is None or doc.user_id != user_id:
            raise DocumentNotFoundError(document_id=doc_id)

        if doc.status != DocumentStatus.READY:
            raise DocumentNotReadyError(document_id=doc_id, status=doc.status)

    return list(found.values())