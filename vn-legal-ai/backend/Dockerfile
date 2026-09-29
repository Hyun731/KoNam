FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY app ./app
COPY ingest ./ingest
COPY eval ./eval
COPY scripts ./scripts
# 색인과 질의의 토큰화가 같아야 하므로 pyvi(vi-nlp)는 색인을 다시 만들 때만 함께 켠다
RUN pip install -e .
COPY alembic.ini ./
COPY alembic ./alembic
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
