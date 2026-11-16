FROM python:3.12.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 STATE_FILE=/data/state.json APP_VERSION=v1.0.0
RUN groupadd -g 10019 app && useradd -r -u 10019 -g app app && mkdir /data && chown app:app /data
WORKDIR /app
COPY main.py .
USER app
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["python", "main.py"]
