#!/usr/bin/env bash
# rebuild.sh
#
# Sets up the app services on the VPS instance and restarts them.
set -euo pipefail
IFS=$'\n\t'

cd /home/ubuntu/apps/quieromudarme/

rm -rf dist/ dbschema/ static/  # quieromudarme/pipelines/{dags,plugins}/
tar -xzf quieromudarme.tar.gz
mv .env.production .env

echo "Building Docker images..."
docker compose --profile init build

# If it's the first time, make sure to run with `--profile init`, e.g. `docker compose --profile init up -d`

echo "Restarting Docker containers..."
docker compose --profile init up -d edgedb postgres edgedb-init
docker compose stop chatbot scheduler
docker compose up -d
