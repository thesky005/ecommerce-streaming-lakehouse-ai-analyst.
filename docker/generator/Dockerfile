FROM python:3.11-slim-bookworm

WORKDIR /app
COPY requirements/generator.txt /tmp/generator.txt
RUN pip install --no-cache-dir -r /tmp/generator.txt
COPY generator ./generator
COPY reference_data ./reference_data

CMD ["python", "-m", "generator"]
