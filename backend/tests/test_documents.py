"""
tests/test_documents_t27.py

Integration tests for T-27:
  - GET  /documents/{document_id}/status
  - GET  /documents
  - DELETE /documents/{document_id}

Fixtures (all defined in conftest.py):
  - async_client:  httpx.AsyncClient bound to the FastAPI app
  - db:            AsyncSession — same session the app uses via dependency override
  - auth_headers:  {"Authorization": "Bearer <token>"} for verified_user
  - verified_user: User ORM object that auth_headers authenticates as

S3 is patched per-test via unittest.mock.patch rather than moto — this lets
us inject specific ClientError codes (NoSuchKey, AccessDenied) cleanly.

All UUID filters pass uuid.UUID objects to SQLAlchemy (not raw strings) —
PostgreSQL handles both, SQLite doesn't.
"""

from __future__ import annotations

import uuid
from datetime import UTC
from unittest.mock import patch

from botocore.exceptions import ClientError
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus

# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _make_document(
    user_id: uuid.UUID,
    *,
    status: DocumentStatus = DocumentStatus.PENDING,
    filename: str = "sample.pdf",
) -> Document:
    """Build an unsaved Document ORM instance."""
    doc_id = uuid.uuid4()
    return Document(
        id=doc_id,
        user_id=user_id,
        filename=filename,
        s3_key=f"{user_id}/{doc_id}/{filename}",
        file_size_bytes=1024,
        mime_type="application/pdf",
        status=status,
    )


async def _seed_document(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    status: DocumentStatus = DocumentStatus.PENDING,
    filename: str = "sample.pdf",
) -> Document:
    """Insert a Document row and return the refreshed ORM object."""
    doc = _make_document(user_id, status=status, filename=filename)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


# --------------------------------------------------------------------------- #
# GET /documents/{document_id}/status                                          #
# --------------------------------------------------------------------------- #


class TestGetDocumentStatus:
    async def test_returns_200_for_own_document(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        doc = await _seed_document(db, verified_user.id, status=DocumentStatus.READY)

        resp = await async_client.get(
            f"/documents/{doc.id}/status",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["document_id"] == str(doc.id)
        assert body["status"] == DocumentStatus.READY.value
        assert body["filename"] == "sample.pdf"
        assert body["file_size_bytes"] == 1024
        assert body["mime_type"] == "application/pdf"
        assert "created_at" in body
        assert "updated_at" in body

    async def test_returns_200_with_error_message_when_failed(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        doc = await _seed_document(db, verified_user.id, status=DocumentStatus.PENDING)
        # Manually force to FAILED with error_message (bypassing state machine for seeding)
        doc.status = DocumentStatus.FAILED.value
        doc.error_message = "PyMuPDF could not decrypt document."
        await db.commit()
        await db.refresh(doc)

        resp = await async_client.get(
            f"/documents/{doc.id}/status",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == DocumentStatus.FAILED.value
        assert body["error_message"] == "PyMuPDF could not decrypt document."

    async def test_returns_404_for_nonexistent_document(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        resp = await async_client.get(
            f"/documents/{uuid.uuid4()}/status",
            headers=auth_headers,
        )

        assert resp.status_code == 404

    async def test_returns_404_for_another_users_document(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
    ) -> None:
        # Seed a document owned by a different user
        other_user_id = uuid.uuid4()
        doc = await _seed_document(db, other_user_id)

        resp = await async_client.get(
            f"/documents/{doc.id}/status",
            headers=auth_headers,
        )

        # Must be 404, not 403 — no resource enumeration
        assert resp.status_code == 404

    async def test_returns_401_without_auth(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        verified_user,
    ) -> None:
        doc = await _seed_document(db, verified_user.id)

        resp = await async_client.get(f"/documents/{doc.id}/status")

        assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# GET /documents                                                               #
# --------------------------------------------------------------------------- #


class TestListDocuments:
    async def test_returns_empty_list_for_new_user(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        resp = await async_client.get("/documents", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["limit"] == 10
        assert body["offset"] == 0
        assert body["pages"] == 0

    async def test_returns_all_own_documents(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        await _seed_document(db, verified_user.id, status=DocumentStatus.READY)
        await _seed_document(db, verified_user.id, status=DocumentStatus.PENDING)
        await _seed_document(db, verified_user.id, status=DocumentStatus.FAILED)

        resp = await async_client.get("/documents", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3

    async def test_does_not_return_other_users_documents(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        other_user_id = uuid.uuid4()
        await _seed_document(db, verified_user.id, status=DocumentStatus.READY)
        await _seed_document(db, other_user_id, status=DocumentStatus.READY)

        resp = await async_client.get("/documents", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1

    async def test_filters_by_status(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        await _seed_document(db, verified_user.id, status=DocumentStatus.READY, filename="a.pdf")
        await _seed_document(db, verified_user.id, status=DocumentStatus.READY, filename="b.pdf")
        await _seed_document(db, verified_user.id, status=DocumentStatus.PENDING, filename="c.pdf")

        resp = await async_client.get(
            "/documents",
            params={"status": "READY"},
            headers=auth_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert all(item["status"] == "READY" for item in body["items"])

    async def test_pagination_limit_and_offset(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        for i in range(5):
            await _seed_document(db, verified_user.id, filename=f"doc_{i}.pdf")

        resp = await async_client.get(
            "/documents",
            params={"limit": 2, "offset": 0},
            headers=auth_headers,
        )
        body = resp.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert body["pages"] == 3  # ceil(5/2)

        resp2 = await async_client.get(
            "/documents",
            params={"limit": 2, "offset": 4},
            headers=auth_headers,
        )
        body2 = resp2.json()
        assert body2["total"] == 5
        assert len(body2["items"]) == 1  # only 1 item left on last page

    async def test_ordered_by_created_at_descending(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        doc_a = await _seed_document(db, verified_user.id, filename="older.pdf")
        doc_b = await _seed_document(db, verified_user.id, filename="newer.pdf")

        # Explicitly backdate doc_a to prevent identical timestamp sorting issues on fast SQLite in-memory tests
        from datetime import datetime, timedelta

        doc_a.created_at = datetime.now(UTC) - timedelta(seconds=10)
        db.add(doc_a)
        await db.commit()

        resp = await async_client.get("/documents", headers=auth_headers)
        body = resp.json()
        ids = [item["document_id"] for item in body["items"]]

        # newest first
        assert ids[0] == str(doc_b.id)
        assert ids[1] == str(doc_a.id)

    async def test_invalid_status_returns_422(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        resp = await async_client.get(
            "/documents",
            params={"status": "INVALID_STATUS"},
            headers=auth_headers,
        )

        assert resp.status_code == 422

    async def test_returns_401_without_auth(
        self,
        async_client: AsyncClient,
    ) -> None:
        resp = await async_client.get("/documents")

        assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# DELETE /documents/{document_id}                                              #
# --------------------------------------------------------------------------- #


class TestDeleteDocument:
    async def test_returns_204_and_removes_db_row(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        doc = await _seed_document(db, verified_user.id)

        with patch("app.services.document_service.s3_client.delete_object") as mock_s3:
            mock_s3.return_value = None  # success

            resp = await async_client.delete(
                f"/documents/{doc.id}",
                headers=auth_headers,
            )

        assert resp.status_code == 204
        assert resp.content == b""

        # DB row must be gone
        result = await db.execute(select(Document).where(Document.id == uuid.UUID(str(doc.id))))
        assert result.scalar_one_or_none() is None

    async def test_s3_delete_called_with_correct_key(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        doc = await _seed_document(db, verified_user.id)
        expected_key = doc.s3_key

        with patch("app.services.document_service.s3_client.delete_object") as mock_s3:
            mock_s3.return_value = None

            await async_client.delete(f"/documents/{doc.id}", headers=auth_headers)

        mock_s3.assert_called_once_with(s3_key=expected_key)

    async def test_treats_s3_nosuchkey_as_success(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        """S3 object already gone → still 204, DB row still deleted."""
        doc = await _seed_document(db, verified_user.id)

        nosuchkey_error = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
            "DeleteObject",
        )

        with patch("app.services.document_service.s3_client.delete_object") as mock_s3:
            mock_s3.side_effect = nosuchkey_error

            resp = await async_client.delete(
                f"/documents/{doc.id}",
                headers=auth_headers,
            )

        assert resp.status_code == 204

        # DB row must still be cleaned up
        result = await db.execute(select(Document).where(Document.id == uuid.UUID(str(doc.id))))
        assert result.scalar_one_or_none() is None

    async def test_treats_s3_404_code_as_success(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        """Some S3 clients return numeric '404' — treat same as NoSuchKey."""
        doc = await _seed_document(db, verified_user.id)

        error_404 = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "DeleteObject",
        )

        with patch("app.services.document_service.s3_client.delete_object") as mock_s3:
            mock_s3.side_effect = error_404

            resp = await async_client.delete(
                f"/documents/{doc.id}",
                headers=auth_headers,
            )

        assert resp.status_code == 204

    async def test_non_404_s3_error_returns_502_and_keeps_db_row(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        """
        S3 returns an unexpected error (e.g. 403 AccessDenied) →
        endpoint must return 502 and leave the DB row intact.
        """
        doc = await _seed_document(db, verified_user.id)

        access_denied = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
            "DeleteObject",
        )

        with patch("app.services.document_service.s3_client.delete_object") as mock_s3:
            mock_s3.side_effect = access_denied

            resp = await async_client.delete(
                f"/documents/{doc.id}",
                headers=auth_headers,
            )

        assert resp.status_code == 502

        # DB row must still exist
        result = await db.execute(select(Document).where(Document.id == uuid.UUID(str(doc.id))))
        assert result.scalar_one_or_none() is not None

    async def test_returns_404_for_nonexistent_document(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        with patch("app.services.document_service.s3_client.delete_object") as mock_s3:
            resp = await async_client.delete(
                f"/documents/{uuid.uuid4()}",
                headers=auth_headers,
            )

        # S3 should never be called if the DB lookup fails
        mock_s3.assert_not_called()
        assert resp.status_code == 404

    async def test_returns_404_for_another_users_document(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
    ) -> None:
        other_user_id = uuid.uuid4()
        doc = await _seed_document(db, other_user_id)

        with patch("app.services.document_service.s3_client.delete_object") as mock_s3:
            resp = await async_client.delete(
                f"/documents/{doc.id}",
                headers=auth_headers,
            )

        mock_s3.assert_not_called()
        assert resp.status_code == 404

        # Other user's row must be untouched
        result = await db.execute(select(Document).where(Document.id == uuid.UUID(str(doc.id))))
        assert result.scalar_one_or_none() is not None

    async def test_returns_401_without_auth(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        verified_user,
    ) -> None:
        doc = await _seed_document(db, verified_user.id)

        resp = await async_client.delete(f"/documents/{doc.id}")

        assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# POST /documents/{document_id}/retry                                         #
# --------------------------------------------------------------------------- #


class TestRetryDocument:
    async def test_retry_success(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        doc = await _seed_document(db, verified_user.id, status=DocumentStatus.FAILED)

        with patch("app.routers.documents.ingest_queue.enqueue") as mock_enqueue:
            resp = await async_client.post(
                f"/documents/{doc.id}/retry",
                headers=auth_headers,
            )

            assert resp.status_code == 202
            body = resp.json()
            assert body["document_id"] == str(doc.id)
            assert body["status"] == DocumentStatus.PROCESSING.value
            mock_enqueue.assert_called_once()

            # Verify status in database
            await db.refresh(doc)
            assert doc.status == DocumentStatus.PROCESSING.value

    async def test_retry_nonexistent_returns_404(
        self,
        async_client: AsyncClient,
        auth_headers: dict,
    ) -> None:
        resp = await async_client.post(
            f"/documents/{uuid.uuid4()}/retry",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_retry_other_users_document_returns_404(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
    ) -> None:
        other_user_id = uuid.uuid4()
        doc = await _seed_document(db, other_user_id, status=DocumentStatus.FAILED)

        resp = await async_client.post(
            f"/documents/{doc.id}/retry",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_retry_non_failed_returns_400(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        # READY state
        doc_ready = await _seed_document(db, verified_user.id, status=DocumentStatus.READY)
        resp = await async_client.post(
            f"/documents/{doc_ready.id}/retry",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "Only FAILED documents can be retried" in resp.json()["detail"]

        # PROCESSING state
        doc_processing = await _seed_document(
            db, verified_user.id, status=DocumentStatus.PROCESSING
        )
        resp2 = await async_client.post(
            f"/documents/{doc_processing.id}/retry",
            headers=auth_headers,
        )
        assert resp2.status_code == 400
        assert "Only FAILED documents can be retried" in resp2.json()["detail"]

    async def test_retry_without_auth_returns_401(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        verified_user,
    ) -> None:
        doc = await _seed_document(db, verified_user.id, status=DocumentStatus.FAILED)
        resp = await async_client.post(f"/documents/{doc.id}/retry")
        assert resp.status_code == 401

    async def test_retry_enqueue_failure_rolls_back_and_returns_503(
        self,
        async_client: AsyncClient,
        db: AsyncSession,
        auth_headers: dict,
        verified_user,
    ) -> None:
        doc = await _seed_document(db, verified_user.id, status=DocumentStatus.FAILED)

        with patch(
            "app.routers.documents.ingest_queue.enqueue", side_effect=Exception("Queue down")
        ):
            resp = await async_client.post(
                f"/documents/{doc.id}/retry",
                headers=auth_headers,
            )

            assert resp.status_code == 503
            assert "Processing queue unavailable" in resp.json()["detail"]

            # Verify status rolled back to FAILED in DB
            await db.refresh(doc)
            assert doc.status == DocumentStatus.FAILED.value
            assert "Processing queue unavailable" in doc.error_message
