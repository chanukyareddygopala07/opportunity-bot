FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SEND_TELEGRAM=false \
    DATABASE_PATH=/app/data/opportunity.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY config ./config
COPY database ./database

RUN mkdir -p /app/data \
    && useradd --system --uid 10001 --no-create-home aawara \
    && chown -R aawara:aawara /app
USER aawara

EXPOSE 8080 8000

CMD ["python", "-m", "src.webapp"]