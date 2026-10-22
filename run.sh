#!/usr/bin/env bash
set -e

# Inviernoticias - Start Python Server (Zero Node, Zero JavaScript)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-3001}"
HOST="${HOST:-0.0.0.0}"

# Check virtual environment
if [ -d "venv" ]; then
    PYTHON_BIN="./venv/bin/python"
    UVICORN_BIN="./venv/bin/uvicorn"
elif [ -d ".venv" ]; then
    PYTHON_BIN="./.venv/bin/python"
    UVICORN_BIN="./.venv/bin/uvicorn"
else
    echo "⚠️  Entorno virtual no detectado. Creando venv..."
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r requirements.txt
    PYTHON_BIN="./venv/bin/python"
    UVICORN_BIN="./venv/bin/uvicorn"
fi

# Check .env file
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "ℹ️  No se encontró .env, copiando desde .env.example..."
    cp .env.example .env
    echo "⚠️  Por favor edita tu archivo .env con tu GEMINI_API_KEY."
fi

echo "=========================================================="
echo "❄️  Iniciando Inviernoticias .mx (Python + FastAPI SSR)"
echo "📡  Servidor escuchando en: http://localhost:$PORT"
echo "🌐  Cero JavaScript en el cliente • Accesible para todos"
echo "=========================================================="

exec "$UVICORN_BIN" app.main:app --host "$HOST" --port "$PORT" --reload
