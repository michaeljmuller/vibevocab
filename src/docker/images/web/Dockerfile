FROM python:3.12-slim
WORKDIR /app
RUN apt-get update -qq && apt-get install -y -qq postgresql-client && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--reload", "--workers", "1", "app:app"]
