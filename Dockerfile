FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml config.py ./
COPY kit ./kit
RUN pip install --no-cache-dir . && useradd --system --uid 10001 --no-create-home kit

USER kit
EXPOSE 8010
CMD ["uvicorn", "kit.panel:app", "--host", "0.0.0.0", "--port", "8010"]

