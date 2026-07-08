dev:
	cd backend && uv run uvicorn app.main:app --reload

dev:
	cd backend && uv run uvicorn app.main:app --reload

test:
	cd backend && pytest

deploy:
	@echo "Deployment script goes here"

benchmark-ingestion:
	cd backend && uv run python scripts/benchmark_ingestion_latency.py --count 20 --size 10
