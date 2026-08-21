import argparse
import asyncio
import csv
import json
from typing import Any

import structlog
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.user import User
from app.services.prompt import build_messages
from app.services.retrieval import retrieve_similar_chunks
from app.utils.openai_client import chat_complete

logger = structlog.get_logger(__name__)


async def generate_qa_pairs(text_chunks: list[str], num_pairs: int = 20) -> list[dict[str, Any]]:
    """Uses LLM to generate Q&A pairs from text chunks."""
    logger.info("Generating Q&A pairs via LLM...")
    prompt = f"""
You are an expert reading comprehension test creator. 
Given the following context fragments extracted from a document, generate {num_pairs} realistic Question and Answer pairs.
The questions should be specific and answerable ONLY using the provided text.
The answer should be concise and directly answer the question.

Output strictly as a JSON array of objects with keys "question" and "answer". Do not wrap in markdown tags like ```json.

Context:
{" ".join(text_chunks)}
"""
    try:
        response_text = await chat_complete(
            [{"role": "user", "content": prompt}],
            model="gpt-4o",  # Using a capable model for generation
            max_tokens=4000,
        )
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith("```"):
            response_text = response_text[3:-3].strip()

        qa_pairs = json.loads(response_text)
        return list(qa_pairs)
    except Exception as e:
        logger.error(f"Failed to generate Q&A pairs: {e}")
        return []


async def grade_answer(question: str, expected_answer: str, generated_answer: str) -> bool:
    """Uses LLM to grade if the generated answer is correct based on the expected answer."""
    prompt = f"""
You are an objective evaluator. You will be provided with a Question, an Expected Answer, and a Generated Answer.
Your task is to determine if the Generated Answer correctly and sufficiently answers the Question, based ONLY on the Expected Answer.
It does not need to match word-for-word, but the core factual information must be correct.

Question: {question}
Expected Answer: {expected_answer}
Generated Answer: {generated_answer}

Respond strictly with a JSON object with two keys:
"is_correct": true or false (boolean)
"reasoning": a short sentence explaining why
"""
    try:
        response_text = await chat_complete(
            [{"role": "user", "content": prompt}], model="gpt-4o-mini", max_tokens=200
        )
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith("```"):
            response_text = response_text[3:-3].strip()

        result = json.loads(response_text)
        return bool(result.get("is_correct", False))
    except Exception as e:
        logger.error(f"Failed to grade answer: {e}")
        return False


async def run_evaluation(user_email: str) -> None:
    async with AsyncSessionLocal() as db:
        # 1. Fetch User
        result = await db.execute(select(User).where(User.email_lower == user_email.lower()))
        user = result.scalar_one_or_none()
        if not user:
            logger.error(f"User with email {user_email} not found.")
            return

        # 2. Fetch a Document
        result = await db.execute(select(Document).where(Document.user_id == user.id))
        documents = result.scalars().all()
        if not documents:
            logger.error(f"No documents found for user {user_email}.")
            return

        doc = documents[0]
        logger.info(f"Selected Document: {doc.filename} (ID: {doc.id})")  # type: ignore[attr-defined]

        # 3. Fetch chunks for generation
        result = await db.execute(select(Chunk).where(Chunk.document_id == doc.id).limit(20))
        chunks = result.scalars().all()
        if not chunks:
            logger.error(f"No chunks found for document {doc.id}.")
            return

        text_chunks = [c.text for c in chunks]  # type: ignore[attr-defined]

        # 4. Generate Dataset
        qa_pairs = await generate_qa_pairs(text_chunks, num_pairs=20)
        if not qa_pairs:
            logger.error("No Q&A pairs generated. Exiting.")
            return

        logger.info(f"Generated {len(qa_pairs)} Q&A pairs.")

        results = []
        correct_count = 0

        # 5 & 6. Pipeline Execution & Grading
        for i, pair in enumerate(qa_pairs):
            question = pair["question"]
            expected = pair["answer"]
            logger.info(f"[{i + 1}/{len(qa_pairs)}] Question: {question}")

            # Run RAG
            retrieved = await retrieve_similar_chunks(
                user_id=user.id, document_ids=[doc.id], query=question, db=db
            )

            messages, _ = build_messages(retrieved, question, history_messages=[])
            generated_answer = await chat_complete(messages, model="gpt-4o-mini", max_tokens=1024)

            # Grade
            is_correct = await grade_answer(question, expected, generated_answer)
            if is_correct:
                correct_count += 1

            results.append(
                {
                    "question": question,
                    "expected_answer": expected,
                    "generated_answer": generated_answer,
                    "is_correct": is_correct,
                }
            )

            logger.info(f"Correct: {is_correct}")

        # 7. Print final score
        accuracy = (correct_count / len(qa_pairs)) * 100
        logger.info("\\n--- EVALUATION COMPLETE ---")
        logger.info(f"Total Questions: {len(qa_pairs)}")
        logger.info(f"Correct Answers: {correct_count}")
        logger.info(f"Accuracy: {accuracy:.1f}%")

        # Save to CSV
        output_file = "rag_evaluation_results.csv"
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["question", "expected_answer", "generated_answer", "is_correct"]
            )
            writer.writeheader()
            for r in results:
                writer.writerow(r)

        logger.info(f"Detailed results saved to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate RAG Pipeline")
    parser.add_argument("email", help="User email to evaluate against")
    args = parser.parse_args()

    asyncio.run(run_evaluation(args.email))
