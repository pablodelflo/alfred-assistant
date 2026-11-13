# Alfred Assistant

Asistente personal doméstico en Python con interfaz web. Proyecto personal, GPL-3.0.
Más contexto en `docs/contexto.md`.

## Requisitos (servidor Linux, siempre encendido)
- Python 3.13 o superior
- PostgreSQL 16 o superior (recomendada la 18)

## Instalación
```bash
# 1. Base de datos
sudo -u postgres psql -c "CREATE USER alfred WITH PASSWORD 'CAMBIAME';"
sudo -u postgres psql -c "CREATE DATABASE alfred OWNER alfred;"

# 2. Entorno e instalación
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .

# 3. Configuración
mkdir config && cp config.ejemplo/servidor.ejemplo.toml config/servidor.toml
# edita config/servidor.toml (contraseña de la base de datos)

# 4. Arranque
python -m alfred.nucleo
```
Abre http://127.0.0.1:8000 (desde fuera de casa, por VPN doméstica): debe verse el catálogo vacío. Si falta algún requisito,
el arranque lo indica y se detiene.

La ruta de configuración puede cambiarse con la variable `ALFRED_CONFIG`.

## Licencia
GPL-3.0. Ver `LICENSE` y `NOTICE`.
