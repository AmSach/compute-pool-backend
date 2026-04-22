FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
EXPOSE 8000
# Auto-create DB tables and seed data on startup
CMD ["sh", "-c", "python -c \"from app.models import Base; from app.database import engine; Base.metadata.create_all(bind=engine); print('DB ready')\" && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
