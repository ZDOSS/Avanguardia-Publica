FROM python:3.12-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -e .

CMD ["sh", "-c", "alembic -c alembic/alembic.ini upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
