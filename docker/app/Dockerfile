# Dashboard + AI analyst: builds showcase.html from the Gold tables, then serves it with the agent API.
FROM python:3.11-slim-bookworm

WORKDIR /app
COPY requirements/ai.txt /tmp/ai.txt
RUN pip install --no-cache-dir -r /tmp/ai.txt
COPY ai ./ai
COPY showcase ./showcase
COPY scripts/build_showcase.py ./scripts/build_showcase.py

ENV AI_SERVER_HOST=0.0.0.0 AI_SERVER_PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "python scripts/build_showcase.py && python -m ai.server"]
