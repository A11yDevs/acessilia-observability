FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml config.py ./
COPY src ./src
COPY frontend ./frontend
COPY docs ./docs
RUN pip install --no-cache-dir . && useradd --system --uid 10001 --no-create-home kit \
    && mkdir -p /app/var && chown kit /app/var

USER kit
EXPOSE 8010
CMD ["uvicorn", "frontend.app:app", "--host", "0.0.0.0", "--port", "8010"]
