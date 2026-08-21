import argparse
import asyncio
import os
import statistics
import sys
import time
import uuid

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import fitz  # PyMuPDF
import httpx

os.environ["DATABASE_URL_SYNC"] = (
    "postgresql+psycopg://pdftalk:pdftalk@localhost:5433/pdftalk"  # pragma: allowlist secret
)
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://pdftalk:pdftalk@localhost:5433/pdftalk"  # pragma: allowlist secret
)

from app.auth.password import hash_password
from app.auth.tokens import create_access_token
from app.db.sync_session import SessionLocal
from app.models.user import User

BASE_URL = os.getenv("API_URL", "http://localhost:8000")


def get_test_users_tokens(num_users: int) -> list[str]:
    """Create N users to bypass the 5-docs-per-minute per-user rate limit."""
    tokens = []
    with SessionLocal() as db:
        for i in range(num_users):
            email = f"benchmark_user_{i}@example.com"
            user = db.query(User).filter(User.email == email).first()
            if not user:
                user = User(
                    id=uuid.uuid4(),
                    email=email,
                    email_lower=email,
                    password_hash=hash_password("Password123!"),
                    is_verified=True,
                    is_active=True,
                )
                db.add(user)
                db.commit()
                db.refresh(user)
            tokens.append(create_access_token(str(user.id)))
    return tokens


def generate_pdf(size_kb: int) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    text = "This is a dummy PDF file for benchmarking ingestion latency. " * 5

    num_iterations = max(1, size_kb)
    for i in range(num_iterations):
        page.insert_text((50, 50 + ((i * 20) % 700)), text)
        if i > 0 and i % 35 == 0:
            page = doc.new_page()

    return bytes(doc.write())


async def upload_document(
    client: httpx.AsyncClient, pdf_bytes: bytes, index: int, token: str
) -> tuple[str, float]:
    start_time = time.time()
    headers = {"Authorization": f"Bearer {token}"}
    files = {"file": (f"benchmark_{index}.pdf", pdf_bytes, "application/pdf")}

    resp = await client.post("/documents/upload", headers=headers, files=files, timeout=30.0)

    if resp.status_code == 429:
        print(f"[-] Document {index} hit rate limit.")
        return "", -1.0

    resp.raise_for_status()
    doc_id = resp.json()["document_id"]
    return doc_id, start_time


async def poll_document(
    client: httpx.AsyncClient, doc_id: str, start_time: float, token: str
) -> float:
    if not doc_id:
        return -1.0

    headers = {"Authorization": f"Bearer {token}"}

    while True:
        resp = await client.get(f"/documents/{doc_id}/status", headers=headers, timeout=10.0)
        if resp.status_code == 200:
            status = resp.json()["status"]
            if status == "READY":
                end_time = time.time()
                return end_time - start_time
            elif status == "FAILED":
                print(f"[-] Document {doc_id} failed ingestion: {resp.json().get('error_message')}")
                return -1.0
        elif resp.status_code == 429:
            pass  # rate limit on status check
        else:
            print(f"[-] Unexpected status code for {doc_id}: {resp.status_code}")

        await asyncio.sleep(1.0)


async def run_benchmark(num_docs: int, size_kb: int) -> None:
    print(f"[*] Generating dummy PDF (approx size factor {size_kb})...")
    pdf_bytes = generate_pdf(size_kb)

    # We need 1 user for every 5 documents to avoid rate limits
    num_users = (num_docs // 5) + 1
    print(f"[*] Authenticating {num_users} test users...")
    tokens = get_test_users_tokens(num_users)

    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        print(f"[*] Uploading {num_docs} documents concurrently...")

        # Dispatch uploads
        upload_tasks = []
        for i in range(num_docs):
            token = tokens[i % num_users]
            upload_tasks.append(upload_document(client, pdf_bytes, i, token))

        upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)

        valid_uploads = []
        for i, res in enumerate(upload_results):
            if isinstance(res, BaseException):
                print(f"[-] Upload {i} failed with exception: {res}")
            else:
                doc_id, start_time = res
                if doc_id:
                    token = tokens[i % num_users]
                    valid_uploads.append((doc_id, start_time, token))

        print(f"[*] Successfully enqueued {len(valid_uploads)} documents.")
        print("[*] Polling for completion...")

        poll_tasks = [
            poll_document(client, doc_id, start_time, token)
            for doc_id, start_time, token in valid_uploads
        ]

        latencies = await asyncio.gather(*poll_tasks, return_exceptions=True)

        valid_latencies = []
        for i, lat in enumerate(latencies):
            if isinstance(lat, BaseException):
                print(f"[-] Polling {i} failed with exception: {lat}")
            elif lat > 0:
                valid_latencies.append(lat)

        if not valid_latencies:
            print("[-] No documents completed successfully.")
            return

        valid_latencies.sort()
        p50 = statistics.median(valid_latencies)
        # Calculate P95 manually or using a library
        p95_idx = int(len(valid_latencies) * 0.95)
        if p95_idx >= len(valid_latencies):
            p95_idx = len(valid_latencies) - 1
        p95 = valid_latencies[p95_idx]
        avg = sum(valid_latencies) / len(valid_latencies)

        print("\n=== Ingestion Latency Benchmark Results ===")
        print(f"Total documents processed : {len(valid_latencies)} / {num_docs}")
        print(f"Minimum Latency           : {min(valid_latencies):.2f} s")
        print(f"Maximum Latency           : {max(valid_latencies):.2f} s")
        print(f"Average Latency           : {avg:.2f} s")
        print(f"P50 Latency               : {p50:.2f} s")
        print(f"P95 Latency               : {p95:.2f} s")
        print("===========================================\n")

        # Cleanup
        print("[*] Cleaning up test documents...")
        for doc_id, _, token in valid_uploads:
            headers = {"Authorization": f"Bearer {token}"}
            await client.delete(f"/documents/{doc_id}", headers=headers)
        print("[*] Cleanup complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark Document Ingestion Pipeline Latency")
    parser.add_argument("--count", type=int, default=20, help="Number of documents to upload")
    parser.add_argument(
        "--size", type=int, default=10, help="Approximate size factor for dummy PDF"
    )
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.count, args.size))
