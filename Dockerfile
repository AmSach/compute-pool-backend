FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

EXPOSE 8080

CMD ["python", "-c", "from app.database import engine; from app.models import Base; Base.metadata.create_all(bind=engine); import uvicorn; uvicorn.run('app.main:app', host='0.0.0.0', port=8080)"]
