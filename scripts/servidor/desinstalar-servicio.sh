#!/usr/bin/env bash
# Para y elimina el servicio de usuario de Alfred. No borra datos ni configuración.
set -euo pipefail

UNIDAD="$HOME/.config/systemd/user/alfred.service"

systemctl --user disable --now alfred.service 2>/dev/null || true
rm -f "$UNIDAD"
systemctl --user daemon-reload
echo "Servicio eliminado. (Si quieres quitar también el «linger»: sudo loginctl disable-linger $USER)"
