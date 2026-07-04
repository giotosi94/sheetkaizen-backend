FROM python:3.11-slim

# Installa LibreOffice (solo Calc) + font per rendering corretto
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-calc \
    libreoffice-core \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Installa dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice
COPY . .

# Variabile per LibreOffice headless
ENV HOME=/tmp

# Start command (stesso di prima)
CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT
``
