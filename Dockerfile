FROM python:3.12-slim

# Tesseract is needed at runtime for receipt OCR (handlers/photo.py -> ocr.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY expense_ai/ ./expense_ai/

# data/, logs/, exports/ are bind-mounted at runtime (see docker-compose.yml);
# create them here too so a bare `docker run` without mounts still works.
RUN mkdir -p data logs exports

CMD ["python", "-m", "expense_ai.bot"]
