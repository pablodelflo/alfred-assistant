#!/usr/bin/env bash
# Instala Alfred como servicio de USUARIO de systemd: arranca con el servidor, se reinicia si
# falla y no depende de tu sesión SSH. No necesita sudo (salvo un comando de «linger», que se indica).
#
#   bash scripts/servidor/instalar-servicio.sh            instala y arranca
#   bash scripts/servidor/instalar-servicio.sh --mostrar  solo muestra el fichero de servicio
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIDAD="$HOME/.config/systemd/user/alfred.service"

unidad() {
cat <<UNIT
[Unit]
Description=Alfred Assistant
# Sin límite de reinicios: si PostgreSQL aún no ha arrancado con el servidor, Alfred reintenta.
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=${RAIZ}
ExecStart=${RAIZ}/.venv/bin/python -m alfred.nucleo
Restart=on-failure
RestartSec=5
# Al parar, Alfred interrumpe los trabajos en curso (hasta gracia_cancelacion_s) y sale.
TimeoutStopSec=30
KillMode=mixed
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
UNIT
}

if [[ "${1:-}" == "--mostrar" ]]; then
    unidad
    exit 0
fi

fallo() { echo "ERROR: $*" >&2; exit 1; }

[[ "$(id -u)" -ne 0 ]] || fallo "Ejecútalo con tu usuario normal, sin sudo (es un servicio de usuario)."
[[ "$RAIZ" != *" "* ]] || fallo "La ruta del proyecto no puede contener espacios: $RAIZ"
[[ -x "$RAIZ/.venv/bin/python" ]] || fallo "No existe el entorno virtual $RAIZ/.venv (ver el README)."
[[ -f "$RAIZ/config/servidor.toml" ]] || fallo "Falta $RAIZ/config/servidor.toml (ver el README)."
command -v systemctl >/dev/null || fallo "No se encontró systemctl."
if pgrep -u "$USER" -f -- '-m alfred\.nucleo$' >/dev/null && ! systemctl --user is-active --quiet alfred.service; then
    fallo "Hay una instancia de Alfred arrancada a mano. Páralas (Ctrl+C en su ventana) y vuelve a ejecutar esto."
fi

mkdir -p "$(dirname "$UNIDAD")"
unidad > "$UNIDAD"
echo "Servicio escrito en $UNIDAD"

systemctl --user daemon-reload || fallo "systemctl --user no responde. Entra por SSH directamente con tu usuario (no con su/sudo)."
systemctl --user enable alfred.service
systemctl --user restart alfred.service  # arranca, o reinicia si ya estaba instalado

# «Linger»: permite que los servicios de usuario arranquen con el servidor sin que inicies sesión.
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || echo no)" != "yes" ]]; then
    echo
    echo "IMPORTANTE: falta un último paso para que arranque solo al reiniciar el servidor. Ejecuta:"
    echo "    sudo loginctl enable-linger $USER"
fi

echo
echo "Esperando a que arranque..."
for _ in $(seq 1 15); do
    [[ "$(systemctl --user is-active alfred.service || true)" == "active" ]] && break
    sleep 1
done
systemctl --user --no-pager --lines=0 status alfred.service || true
echo
echo "Últimas líneas del registro:"
journalctl --user -u alfred.service -n 12 --no-pager 2>/dev/null || echo "(no se pudo leer el registro; prueba: journalctl --user -u alfred -n 50)"
echo
echo "Comandos útiles (siempre con --user):"
echo "    systemctl --user status alfred        journalctl --user -u alfred -f"
echo "    systemctl --user restart alfred       systemctl --user stop alfred"
