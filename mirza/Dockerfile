FROM python:3.12-slim

# system deps for asyncpg + qrcode
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# deps first for layer caching
COPY pyproject.toml README.md ./
COPY mirza ./mirza
# optional but keeps pip cache small
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir . \
 && pip install --no-cache-dir "qrcode[pil]"

# non-root
RUN useradd -m mirza
USER mirza

ENV MIRZA_DB__DRIVER=postgresql+asyncpg
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import httpx; httpx.get('http://127.0.0.1:8080/healthz', timeout=3).raise_for_status()" || exit 1

CMD ["python", "-m", "mirza", "--webhook"]
