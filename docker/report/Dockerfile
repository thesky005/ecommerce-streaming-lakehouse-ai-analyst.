FROM python:3.11-slim-bookworm

WORKDIR /app
COPY requirements/report.txt /tmp/report.txt
RUN pip install --no-cache-dir -r /tmp/report.txt
COPY .streamlit ./.streamlit
COPY report ./report

EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "report/Home.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
