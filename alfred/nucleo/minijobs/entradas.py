"""Entradas declarativas de un minijob: de ellas salen el formulario y la validación.

Tipos: "ficheros", "entero", "booleano", "seleccion".
"""
import importlib.util
from dataclasses import dataclass, field

TIPOS = ("ficheros", "entero", "booleano", "seleccion")


def dependencias_faltantes(modulos) -> list[str]:
    faltan = []
    for modulo in modulos:
        try:
            if importlib.util.find_spec(modulo) is None:
                faltan.append(modulo)
        except (ImportError, ValueError):
            faltan.append(modulo)
    return faltan


@dataclass(frozen=True)
class Opcion:
    valor: str
    etiqueta: str
    dependencias: tuple[str, ...] = ()

    @property
    def disponible(self) -> bool:
        return not dependencias_faltantes(self.dependencias)


@dataclass(frozen=True)
class Campo:
    id: str
    tipo: str
    etiqueta: str
    ayuda: str = ""
    obligatorio: bool = False
    defecto: object = None
    minimo: int | None = None
    maximo: int | None = None
    opciones: tuple[Opcion, ...] = ()
    extensiones: tuple[str, ...] = ()

    @property
    def opciones_disponibles(self) -> tuple[Opcion, ...]:
        return tuple(o for o in self.opciones if o.disponible)


def parsear_campos(lista: list[dict]) -> tuple[Campo, ...]:
    """Convierte la lista `[[entradas]]` del manifiesto; lanza ValueError si es inválida."""
    campos, vistos = [], set()
    for bruto in lista:
        try:
            id_, tipo, etiqueta = bruto["id"], bruto["tipo"], bruto["etiqueta"]
        except KeyError as e:
            raise ValueError(f"entrada sin el campo {e}") from e
        if tipo not in TIPOS:
            raise ValueError(f"entrada «{id_}»: tipo «{tipo}» desconocido (usa: {', '.join(TIPOS)})")
        if id_ in vistos:
            raise ValueError(f"entrada «{id_}» repetida")
        vistos.add(id_)
        opciones = tuple(Opcion(o["valor"], o["etiqueta"], tuple(o.get("dependencias", ())))
                         for o in bruto.get("opciones", ()))
        if tipo == "seleccion" and not opciones:
            raise ValueError(f"entrada «{id_}»: una selección necesita opciones")
        campos.append(Campo(id=id_, tipo=tipo, etiqueta=etiqueta, ayuda=bruto.get("ayuda", ""),
                            obligatorio=bool(bruto.get("obligatorio", False)),
                            defecto=bruto.get("defecto"), minimo=bruto.get("minimo"),
                            maximo=bruto.get("maximo"), opciones=opciones,
                            extensiones=tuple(e.lower() for e in bruto.get("extensiones", ()))))
    return tuple(campos)


def problemas_de_disponibilidad(campos: tuple[Campo, ...]) -> list[str]:
    """Qué impide ofrecer el minijob: selecciones obligatorias sin ninguna opción utilizable."""
    problemas = []
    for c in campos:
        if c.tipo == "seleccion" and c.obligatorio and not c.opciones_disponibles:
            faltan = sorted({d for o in c.opciones for d in dependencias_faltantes(o.dependencias)})
            problemas.append(f"{c.etiqueta}: faltan dependencias ({', '.join(faltan)})")
    return problemas


@dataclass
class Validacion:
    valores: dict = field(default_factory=dict)
    errores: dict = field(default_factory=dict)  # id del campo -> mensaje

    @property
    def ok(self) -> bool:
        return not self.errores


def validar(campos: tuple[Campo, ...], enviado: dict) -> Validacion:
    """Valida los valores recibidos de un formulario (todos como texto). Ignora los campos de ficheros."""
    v = Validacion()
    for c in campos:
        if c.tipo == "ficheros":
            continue
        bruto = enviado.get(c.id)
        if c.tipo == "booleano":
            v.valores[c.id] = str(bruto).lower() in ("on", "true", "1", "si", "sí")
        elif c.tipo == "entero":
            texto = "" if bruto is None else str(bruto).strip()
            if texto == "":
                if c.defecto is not None:
                    v.valores[c.id] = int(c.defecto)
                elif c.obligatorio:
                    v.errores[c.id] = "Obligatorio"
                continue
            try:
                n = int(texto)
            except ValueError:
                v.errores[c.id] = "Debe ser un número entero"
                continue
            if c.minimo is not None and n < c.minimo or c.maximo is not None and n > c.maximo:
                v.errores[c.id] = f"Debe estar entre {c.minimo} y {c.maximo}"
                continue
            v.valores[c.id] = n
        elif c.tipo == "seleccion":
            valor = (str(bruto).strip() if bruto not in (None, "") else c.defecto)
            validos = {o.valor for o in c.opciones_disponibles}
            if valor is None:
                if c.obligatorio:
                    v.errores[c.id] = "Obligatorio"
            elif valor not in validos:
                v.errores[c.id] = "Opción no disponible"
            else:
                v.valores[c.id] = valor
    return v
