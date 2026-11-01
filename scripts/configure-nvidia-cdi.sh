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
Environment=NVIDIA_CTK_CDI_GENERATE_OUTPUT_FORMAT=json
Environment=NVIDIA_CTK_CDI_OUTPUT_FILE_PATH=/etc/cdi/nvidia.json
EOF
# Validate the new spec before replacing the currently working one.
cdi_tmp=$(mktemp /etc/.pcb-nvidia-cdi.XXXXXX)
trap 'rm -f "$cdi_tmp"' EXIT
nvidia-ctk cdi generate --feature-flag no-additional-gids-for-device-nodes --format=json --output="$cdi_tmp"
python3 -m json.tool "$cdi_tmp" >/dev/null
chmod 644 "$cdi_tmp"
mv "$cdi_tmp" /etc/cdi/nvidia.json
# Avoid duplicate device definitions from the previous generated specs.
# Keep backups outside the .yaml/.json extensions scanned by CDI.
for old_spec in /etc/cdi/nvidia.yaml /var/run/cdi/nvidia.yaml; do
    if [ -f "$old_spec" ]; then
        backup=$(mktemp "${old_spec}.backup.XXXXXX")
        mv "$old_spec" "$backup"
    fi
done
systemctl daemon-reload
systemctl restart nvidia-cdi-refresh.service
nvidia-ctk cdi list
