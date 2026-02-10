#!/bin/bash
# Script to run the Django development server with the virtual environment activated

cd "$(dirname "$0")"
source venv/bin/activate

# Check if port 8000 is already in use
PORT=8000
if lsof -ti:$PORT > /dev/null 2>&1; then
    echo "Port $PORT is already in use."
    read -p "Do you want to kill the process using port $PORT? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Killing process on port $PORT..."
        kill $(lsof -ti:$PORT)
        sleep 1
    else
        echo "Using alternative port 8001..."
        PORT=8001
    fi
fi

python manage.py runserver $PORT
