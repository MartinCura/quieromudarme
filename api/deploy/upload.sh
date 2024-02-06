#!/usr/bin/env bash
# upload.sh
#
# Creates a tarball of the app and uploads it to the EC2 instance,
# together with other necessary files for this app to run.
set -euo pipefail
IFS=$'\n\t'

# ec2_instance_id=${1:-"i-0eb8d32faac51a6f6"}
# echo "EC2 instance ID: ${ec2_instance_id}"
# vps_ip=$(aws --profile tincho ec2 describe-instances \
#   --instance-ids ${ec2_instance_id} --query 'Reservations[*].Instances[*].PublicIpAddress' --output text)
vps_ip="149.50.137.147"
vps_port="5348"
echo "EC2 instance IP: ${vps_ip}, port: ${vps_port}"
echo

rm -rf ./dist/*
poetry build

# Create a tarball of the app
tar -czf deploy/quieromudarme.tar.gz \
  --exclude='qm_airflow/logs' \
  --exclude='**/__pycache__' \
  dist/ static/ \
  dbschema/ qm_airflow/ \
  .env.production pyproject.toml poetry.lock \
  Dockerfile docker-compose.yaml README.md \
  quieromudarme/
# TODO: temporarily simply uploading all python code

# Upload to the EC2 instance
scp -i ~/.ssh/quieromudarme-kp.pem -P ${vps_port} ./deploy/quieromudarme.tar.gz "ubuntu@${vps_ip}:/home/ubuntu/apps/quieromudarme/"

# Extract the tarball and set up the app on the EC2 instance
ssh -i ~/.ssh/quieromudarme-kp.pem -p ${vps_port} "ubuntu@${vps_ip}" 'bash -s' < ./deploy/rebuild.sh

echo
echo "Done!"
