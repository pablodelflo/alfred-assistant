# Alfred Assistant

Asistente personal doméstico en Python con interfaz web. Proyecto personal, GPL-3.0.
Un único servidor siempre encendido, un núcleo pequeño y "minijobs" enchufables.
Más contexto en `docs/contexto.md`; cómo escribir un minijob, en `docs/contrato-minijob.md`.

## Qué hace hoy
- Catálogo de minijobs con formularios generados desde su manifiesto TOML.
- Cola de trabajos con progreso, cancelación, reintento y recuperación tras reinicios.
- Minijob `conversor_medios`: HEIC → JPG por subida y descarga (individual o ZIP); los resultados caducan (6 h por defecto).
- Acceso con un único usuario administrador (sesión por cookie).
- Servicio systemd de usuario para que arranque solo.

## Requisitos (servidor Linux, siempre encendido)
- Python 3.13 o superior
- PostgreSQL 16 o superior (recomendada la 18)

## Instalación (probada en Oracle Linux 9)

### 1. PostgreSQL (repositorio oficial PGDG)
El módulo `postgresql` del sistema puede chocar con otros paquetes (por ejemplo Kea DHCP, que
depende de `libpq`). Por eso se usa el repositorio PGDG. Sigue las instrucciones de
<https://www.postgresql.org/download/linux/redhat/> para tu versión (recomendada la 18), inicializa
el clúster (`postgresql-18-setup initdb`), activa y arranca el servicio y comprueba que
`pg_hba.conf` admite contraseña (`scram-sha-256`) para conexiones locales.

Crea usuario y base de datos (usa comillas simples en la contraseña: un `$` se expandiría en bash):
```bash
sudo -u postgres psql -c "CREATE USER alfred WITH PASSWORD 'CAMBIAME';"
sudo -u postgres psql -c 'CREATE DATABASE "alfred-assistant" OWNER alfred;'
```

### 2. Entorno Python
```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Configuración
```bash
mkdir config && cp config.ejemplo/servidor.ejemplo.toml config/servidor.toml
# edita config/servidor.toml: url de la base de datos y, si quieres, el resto de valores
```
La ruta puede cambiarse con la variable `ALFRED_CONFIG`. Los valores se leen en cada petición; en el
futuro se podrán editar desde una pantalla de Ajustes.

### 4. Esquema y usuario administrador
```bash
python -m alfred.nucleo.datos actualizar
python -m alfred.nucleo.usuarios crear        # crea «admin» y pide la contraseña
```

### 5. Primer arranque (prueba)
```bash
python -m alfred.nucleo
```
Debe mostrar los seis comprobaciones `[ok]` y quedarse sirviendo en http://127.0.0.1:8000.
Si falta algún requisito, el arranque lo indica y se detiene.

### 6. Acceso desde otro equipo
Alfred escucha solo en `127.0.0.1` y va por HTTP sin cifrar: no lo expongas a Internet.
Desde el equipo de sobremesa, abre un túnel SSH:
```bash
ssh -L 8000:127.0.0.1:8000 usuario@servidor
```
y entra en http://127.0.0.1:8000 (o usa la VPN doméstica). Si algún día lo sirves por HTTPS,
pon `cookie_segura = true`.

### 7. Servicio systemd (de usuario)
Es un servicio de *usuario* y no de sistema por SELinux.
```bash
bash scripts/servidor/instalar-servicio.sh
sudo loginctl enable-linger $USER      # arranca al iniciar la máquina sin sesión abierta
systemctl --user status alfred
journalctl --user -u alfred -f
```
Para quitarlo: `bash scripts/servidor/desinstalar-servicio.sh`.

## Actualizar
```bash
git pull
source .venv/bin/activate && pip install -e .
python -m alfred.nucleo.datos actualizar
systemctl --user restart alfred
```

## Utilidades de consola
- `python -m alfred.nucleo.datos [estado|actualizar]`
- `python -m alfred.nucleo.usuarios [crear|cambiar-clave|cerrar-sesiones|listar]`
- `python -m alfred.nucleo.trabajos [crear|listar|cancelar|reintentar]`

## Tests
```bash
pip install -e ".[dev]"
ALFRED_TEST_DB_URL=postgresql://... pytest
```
(Sin `ALFRED_TEST_DB_URL` se omiten los tests que necesitan PostgreSQL.)

## Licencia
GPL-3.0. Ver `LICENSE` y `NOTICE`.
