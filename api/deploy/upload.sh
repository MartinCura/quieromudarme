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
ssh_key_path="~/.ssh/id_vps_qm.pub"
echo "VPS instance IP: ${vps_ip}, port: ${vps_port}, SSH key path: ${ssh_key_path}\n"

rm -rf ./dist/*
uv build

# Create a tarball of the app
tar -czf quieromudarme.tar.gz \
  --exclude='**/logs' --exclude='**/__pycache__' \
  deploy/ dist/ static/ dbschema/ quieromudarme/pipelines/ \
  .env.production pyproject.toml uv.lock \
  docker/ compose.yaml \
  quieromudarme/ README.md
# TODO: temporarily simply uploading all python code

# Upload to the VPS instance
scp -i ${ssh_key_path} -P ${vps_port} quieromudarme.tar.gz "ubuntu@${vps_ip}:/home/ubuntu/apps/quieromudarme/"

# Extract the tarball and set up the app on the VPS instance
ssh -i ${ssh_key_path} -p ${vps_port} "ubuntu@${vps_ip}" 'bash -s' < ./deploy/rebuild.sh

rm quieromudarme.tar.gz
echo
echo "Done!"
