FROM python:3.13-slim

WORKDIR /app

# libmagic1 is required by python-magic for MIME/magic-byte detection.
# Must be installed at the OS level — python-magic is just a binding.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./

RUN pip install uv

RUN uv sync --frozen

COPY . .

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
