#!/usr/bin/env bash
# rebuild.sh
#
# Sets up the app services on the VPS instance and restarts them.
set -euo pipefail
IFS=$'\n\t'

cd /home/ubuntu/apps/quieromudarme/

rm -rf dist/ dbschema/ static/  # quieromudarme/etl/{dags,plugins}/
tar -xzf quieromudarme.tar.gz
mv .env.production .env

echo "Building Docker images..."
docker compose build

# If it's the first time, make sure to run with `--profile init`, e.g. `docker compose --profile init up -d`

echo "Restarting Docker containers..."
docker compose --profile init up -d edgedb-init airflow-init
docker compose stop chatbot airflow-scheduler
docker compose up -d
