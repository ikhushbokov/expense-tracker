FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The local /sync screenshot OCR engine (expense_ai/card_ocr.py). --no-deps is
# deliberate: its declared opencv-python dependency is already satisfied by the
# headless build pinned in requirements.txt, which needs no system libraries --
# see the comment there.
RUN pip install --no-cache-dir --no-deps rapidocr-onnxruntime==1.4.4

COPY expense_ai/ ./expense_ai/

# data/, logs/, exports/ are bind-mounted at runtime (see docker-compose.yml);
# create them here too so a bare `docker run` without mounts still works.
RUN mkdir -p data logs exports

CMD ["python", "-m", "expense_ai.bot"]
