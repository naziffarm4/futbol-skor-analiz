FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces standardı: UID 1000 (root olmayan kullanıcı) ve yazılabilir çalışma dizini
RUN useradd -m -u 1000 user \
    && mkdir -p /app/engine/data \
    && chown -R user:user /app

USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR /app

COPY --chown=user engine/requirements.txt /app/engine/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/engine/requirements.txt

COPY --chown=user engine /app/engine
COPY --chown=user app.py README.md /app/

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
