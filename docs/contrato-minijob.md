# Contrato del minijob

Resumen de la sección 3 de `contexto.md`, con lo ya implementado.

Un minijob es una carpeta en `alfred/minijobs/` (o en `minijobs_personales/`) con dos ficheros.

## `manifiesto.toml`
Obligatorios: `id` (igual al nombre de la carpeta), `nombre`, `descripcion`, `categoria`,
`version`, `peso` (`"ligero"` o `"pesado"`, limita la concurrencia) y `tiempo_maximo`
(segundos; al superarlo el núcleo corta el trabajo y lo marca como fallido).

Opcional: `conservacion_horas` (número; horas que se conservan los ficheros del trabajo desde que
termina, `0` = no caducan). Si falta, se usa `almacenamiento.conservacion_horas` de la configuración
(6 por defecto). Al caducar se borra la carpeta del trabajo; su fila del historial se conserva.

## `ejecutar.py`
Define `ejecutar(ctx: Contexto) -> Informe`. Solo importa de `alfred.comun.contrato`.

- `ctx.entradas`: las entradas ya validadas.
- `ctx.carpeta_entrada`, `ctx.carpeta_temporal`, `ctx.carpeta_salida`: su carpeta aislada.
  Los temporales se escriben solo en `carpeta_temporal`.
- `ctx.progreso(porcentaje, mensaje)`: informa del avance.
- `ctx.comprobar_cancelacion()`: lanza `Cancelado` si se pidió cancelar. Llamarlo a menudo;
  si el minijob no responde, el núcleo lo corta tras `gracia_cancelacion_s`.
- Devuelve `Informe(resumen, resultados, fallos)`. Si `fallos` no está vacío, el trabajo
  termina «con avisos». Un fichero corrupto no debe detener el lote: va a `fallos`.
- Error con mensaje claro para el usuario: `raise ErrorUsuario("...")`. Cualquier otra
  excepción se guarda como detalle técnico y el usuario ve un mensaje genérico.

El minijob no accede a la base de datos ni habla con otros minijobs.
