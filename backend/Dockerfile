FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    xvfb \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DISPLAY=:99
ENV CHROMIUM_PATH=/usr/bin/chromium

# Start Xvfb (virtual display for headless Chrome login window) then start uvicorn
CMD Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp & uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
