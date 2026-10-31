#!/bin/bash
# NVIDIA Container Toolkit only. Does not install or replace a GPU driver.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this script with sudo to install NVIDIA container integration.' >&2
    exit 1
fi
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg
key_tmp=$(mktemp)
list_tmp=$(mktemp)
trap 'rm -f "$key_tmp" "$list_tmp"' EXIT
curl --fail --location --retry 3 https://nvidia.github.io/libnvidia-container/gpgkey -o "$key_tmp"
gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg "$key_tmp"
curl --fail --location --retry 3 https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list -o "$list_tmp"
sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' "$list_tmp" > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update
apt-get install -y nvidia-container-toolkit
mkdir -p /etc/cdi
bash "$(dirname "$0")/configure-nvidia-cdi.sh"
