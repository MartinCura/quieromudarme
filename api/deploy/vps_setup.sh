#!/usr/bin/env bash
# ec2_setup.sh
#
# To be run manually on a fresh ~EC2~ instance with Ubuntu 22.04.
# Installs Docker, Docker Compose, and sets up the environment for the app.
set -euo pipefail
IFS=$'\n\t'

# Run manually
exit 1

# If in DonWeb or another with only root access by default, create a user
adduser ubuntu
# and edit /etc/sudoers to add the appropriate line
# Then re-login as that user, make sure you're in /home/ubuntu
# Ideally also create SSH keys and add them to the authorized_keys file
# Steps:
# ssh-keygen -t rsa -b 4096 -C ...
# cat ~/.ssh/id_rsa.pub >>~/.ssh/authorized_keys ?
# chmod 600 ~/.ssh/authorized_keys ?

# Update and upgrade packages
sudo apt update
sudo apt upgrade -y

# Install Docker
## Add Docker's official GPG key
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
## Add the repository to Apt sources
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" |
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
## Install
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
## Add the current user to the docker group
sudo usermod -aG docker $USER
newgrp docker
sudo service docker start

# Install lazydocker
curl https://raw.githubusercontent.com/jesseduffield/lazydocker/master/scripts/install_update_linux.sh | bash
echo "PATH=${PATH}:$HOME/.local/bin" >>~/.bashrc
cat <<EOF >~/.config/lazydocker/config.yml
gui:
  #wrapMainPanel: false
  legacySortContainers: true
  expandFocusedSidePanel: true
  scrollHeight: 5
  sidePanelWidth: 0.27
  containerStatusHealthStyle: "icon"
commandTemplates:
  dockerCompose: docker compose
EOF

mkdir -p /home/ubuntu/apps/quieromudarme/

# Reboot just in case
sudo reboot
