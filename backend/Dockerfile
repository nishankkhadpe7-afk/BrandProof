# BrandProof API with Tesseract OCR (Render, Fly, any Docker host)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /srv/backend/
COPY samples/ /srv/samples/
ENV PORT=8000 BRANDPROOF_AUTOSEED=1
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
