#!/bin/bash
set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_DIR="./logs"
mkdir -p "$LOG_DIR"

CENTRAL_LOG="${LOG_DIR}/centralized_${TIMESTAMP}.log"
touch "$CENTRAL_LOG"

SERVICES=(web db redis mongodb qdrant ollama)

echo "Starting log capture for run ${TIMESTAMP}"
echo "Logs will be written to ${LOG_DIR}/"
echo "Press Ctrl+C to stop capturing (containers keep running)."

PIDS=()

# One file per container, each following that container's raw output
for svc in "${SERVICES[@]}"; do
    SVC_LOG="${LOG_DIR}/${svc}_${TIMESTAMP}.log"
    docker-compose logs -f -t "$svc" > "$SVC_LOG" 2>&1 &
    PIDS+=($!)
    echo "  ${svc} -> ${SVC_LOG}"
done

# One combined file, all services interleaved - docker-compose already
# prefixes each line with the service name when following more than one
# service, so no extra tagging is needed here.
docker-compose logs -f -t > "$CENTRAL_LOG" 2>&1 &
PIDS+=($!)
echo "  all services (combined) -> ${CENTRAL_LOG}"

wait "${PIDS[@]}"
echo "Capture finished for run ${TIMESTAMP}"
