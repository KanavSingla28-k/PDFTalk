dev:
	cd backend && uv run uvicorn app.main:app --reload

test:
	cd backend && pytest

deploy:
	@echo "Deployment script goes here"
