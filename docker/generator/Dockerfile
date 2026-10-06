FROM python:3.11-slim-bookworm

WORKDIR /app
COPY generator ./generator
COPY reference_data ./reference_data

CMD ["python", "-m", "generator", "--live"]
