# Cambios

## 0.1.0
- Cimientos: estructura del proyecto, licencia GPL-3.0, configuración TOML, comprobaciones de arranque.
- Núcleo mínimo: persistencia en PostgreSQL (SQLAlchemy + Alembic), cola de trabajos con un subproceso por trabajo,
  progreso, cancelación (SIGTERM y luego SIGKILL), reintento y recuperación de trabajos interrumpidos.
- Catálogo de minijobs con manifiestos TOML y formularios generados; zona temporal con limpieza por caducidad
  (6 h por defecto, configurable y ajustable por minijob).
- Minijob `conversor_medios`: HEIC → JPG con calidad, metadatos, GPS y redimensionado opcionales.
- Interfaz web: subida de ficheros, lista y detalle de trabajos, descarga individual o en ZIP.
- Acceso con usuario administrador (scrypt, sesión por cookie, protección CSRF, límite de intentos).
- Servicio systemd de usuario con scripts de instalación y desinstalación.
- PostgreSQL 16 como mínimo (recomendada la 18).
