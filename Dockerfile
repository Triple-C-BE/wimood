FROM python:3.13-slim
LABEL authors="Nick Corné - Triple-C"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (excluding venv, tests, logs)
COPY main.py .env.example ./
COPY config /app/config
COPY integrations /app/integrations
COPY utils /app/utils

# Create data folder
RUN mkdir data
VOLUME /app/data

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
