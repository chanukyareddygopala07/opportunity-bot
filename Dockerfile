FROM python:3.12-slim

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
COPY scripts ./scripts

RUN mkdir -p /app/data

EXPOSE 8080

CMD ["python", "-m", "src.webapp"]