#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Configuration (Edit these for your server)
SERVER_IP="192.168.1.33"
SERVER_USER="yg"
DEPLOY_DIR="~/apps/inviernoticias"

echo "=== Deploying Inviernoticias (Python/FastAPI) to Server ($SERVER_IP) ==="

# Check connection
if ! ping -c 1 "$SERVER_IP" > /dev/null 2>&1; then
    echo "Error: Server $SERVER_IP is not reachable. Check your local network connection."
    exit 1
fi

echo "1. Syncing project files with remote server using rsync..."
# Sync files, excluding python virtual environments, git history, and local database files
rsync -avz --delete \
          --exclude 'venv' \
          --exclude '.venv' \
          --exclude '__pycache__' \
          --exclude '*.pyc' \
          --exclude '.git' \
          --exclude '.env' \
          --exclude 'inviernoticias.db*' \
          ./ "$SERVER_USER@$SERVER_IP:$DEPLOY_DIR"

echo "2. Checking remote configuration..."
if [ -f .env ]; then
    echo "Copying local .env to remote server..."
    scp .env "$SERVER_USER@$SERVER_IP:$DEPLOY_DIR/.env"
else
    echo "Warning: No .env configuration file was found locally. You will need to"
    echo "manually populate $DEPLOY_DIR/.env on your server with your keys."
fi

echo "3. Starting Docker container on remote server..."
ssh "$SERVER_USER@$SERVER_IP" "cd $DEPLOY_DIR && docker compose down && docker compose up -d --build"

echo "=== Deployment Completed Successfully ==="
echo "You can access the app at: http://$SERVER_IP:3001"
