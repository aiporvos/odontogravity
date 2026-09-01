FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Sin esto la salida queda en el buffer y, si el proceso muere, los ultimos
# logs (los del error) no llegan nunca a `docker logs` ni al panel de Dokploy.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Que version quedo adentro. Sirve para verificar despues de un deploy que el
# contenedor tomo el codigo nuevo: los arreglos internos no cambian nada visible
# desde afuera, y sin esto no habia forma de saberlo. Es opcional: si el build
# no pasa el arg, /api/health igual informa la fecha del codigo.
ARG GIT_COMMIT=""
ENV GIT_COMMIT=$GIT_COMMIT

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Run with uvicorn
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
