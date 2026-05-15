#!/bin/bash
# Pipeline de prospección — ejecutado por cron
# Logs en data/cron.log

PROJECT="/Users/Bastian/scrapy/actualyza-prospecting"
PYTHON="/usr/bin/python3"
LOG="$PROJECT/data/cron.log"

mkdir -p "$PROJECT/data"

echo "" >> "$LOG"
echo "=================================================" >> "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] CRON INICIADO" >> "$LOG"
echo "=================================================" >> "$LOG"

cd "$PROJECT" && "$PYTHON" -m pipeline.orchestrator >> "$LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] CRON FINALIZADO" >> "$LOG"
