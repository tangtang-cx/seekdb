FROM python:3.11-slim

WORKDIR /app

# Only streamlit is required, and only for the optional Streamlit UI.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# The whole project lives at /app (run.py sits next to app.py).
COPY . /app

ENV PYTHONUNBUFFERED=1 \
    PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=12 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8501/health')"

# Zero-dependency entry: serves the interactive reviewer + /health + /api/review.
# Use `--streamlit` (or `streamlit run app.py`) for the full Streamlit UI.
CMD ["python", "run.py"]
