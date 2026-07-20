#!/bin/bash
set -e

echo "Starting containers..."
docker-compose up -d --build

echo "Waiting for services to become healthy..."
sleep 5

echo "Starting log capture..."
./capture_logs.sh &

echo ""
echo "Saarthi is up. Log capture is running in the background for this session."
echo "To stop log capture without stopping containers: pkill -f capture_logs.sh"
