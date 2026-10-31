#!/bin/bash
# NVIDIA's supported compatibility setting for Podman < 5.1.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run with sudo: updates the root-owned CDI configuration.' >&2
    exit 1
fi
mkdir -p /etc/cdi /etc/systemd/system/nvidia-cdi-refresh.service.d
cat > /etc/systemd/system/nvidia-cdi-refresh.service.d/50-pcb-thermal-compat.conf <<'EOF'
[Service]
Environment=NVIDIA_CTK_CDI_GENERATE_FEATURE_FLAGS=no-additional-gids-for-device-nodes
EOF
nvidia-ctk cdi generate --feature-flag no-additional-gids-for-device-nodes --output=/etc/cdi/nvidia.yaml
systemctl daemon-reload
systemctl restart nvidia-cdi-refresh.service
nvidia-ctk cdi list
