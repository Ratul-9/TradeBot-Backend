#!/bin/bash

# Wait for database to be ready (optional safety step)
echo "Waiting for database to be ready..."
sleep 5

# Apply migrations
echo "Running migrations..."
python manage.py migrate

# Start Gunicorn server
echo "Starting Gunicorn..."
exec gunicorn tradebot-backend.wsgi:application
