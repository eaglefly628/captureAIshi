# Cloud-deploy image for the captureAIshi client demo (DEMOAISHI=1).
# Real-capture deps (renderdoccmd, OBS, cv2, pywebview, ...) are
# intentionally absent -- the demo path never imports them.
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DEMOAISHI=1 \
    DEMOAISHI_SCENARIO=batman_ak \
    PORT=8080

WORKDIR /app

COPY requirements-demo.txt ./
RUN pip install -r requirements-demo.txt

# Source. .dockerignore prunes the heavy dirs that demo mode never touches
# (renderdoc/, 3rdparty/, output/, tests/, docs/refCode/, etc.).
COPY . ./

EXPOSE 8080

# Single Flask process is fine for demo traffic. Threads=4 lets the demo
# DemoSession run concurrently with /api/status long polls.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 60 web_ui:app"]
