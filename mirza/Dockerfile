FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY mirza ./mirza
RUN pip install --no-cache-dir .
ENV MIRZA_DB__DRIVER=postgresql+asyncpg
CMD ["python", "-m", "mirza"]
