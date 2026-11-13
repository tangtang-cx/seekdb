FROM python:3.11-slim

# 不装任何第三方包：应用默认入口 run.py 只用标准库，离线环境也能 build & run。
# 需要完整 Streamlit 界面时再自行 `pip install -r requirements.txt`。
WORKDIR /app
COPY . /app

ENV PYTHONUNBUFFERED=1 \
    PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=12 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8501/health')"

CMD ["python", "run.py", "--serve"]
