# =============================================================================
# === backend/Dockerfile ===
# Same layer-ordering discipline as frontend/Dockerfile.dev —
# requirements.txt copied and installed BEFORE the rest of the app,
# so editing a Python file doesn't force a full pip reinstall on
# every rebuild.
# =============================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/base.txt requirements/base.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements/base.txt \
    && pip install --no-cache-dir gunicorn

COPY . .

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
