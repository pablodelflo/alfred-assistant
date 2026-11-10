"""HEIC/HEIF → JPG con Pillow y pillow-heif (sin herramientas externas)."""
from pathlib import Path

from . import Conversion

EXIF_GPS = 0x8825


def convertir(origen: Path, destino: Path, opciones: dict) -> None:
    import pillow_heif
    from PIL import Image, ImageOps

    pillow_heif.register_heif_opener()
    with Image.open(origen) as bruta:
        bruta.load()
        # Aplica la orientación para que el JPG se vea bien aunque se descarten los metadatos.
        imagen = ImageOps.exif_transpose(bruta)
        icc = bruta.info.get("icc_profile")
    exif = imagen.getexif() if opciones["conservar_metadatos"] else None
    if exif is not None and opciones["quitar_gps"]:
        exif.pop(EXIF_GPS, None)
    if imagen.mode != "RGB":
        imagen = imagen.convert("RGB")
    lado = opciones["redimensionar"]
    if lado and max(imagen.size) > lado:
        imagen.thumbnail((lado, lado), Image.Resampling.LANCZOS)

    parametros = {"quality": opciones["calidad"], "optimize": True}
    if icc:
        parametros["icc_profile"] = icc
    if exif is not None and len(exif):
        parametros["exif"] = exif
    imagen.save(destino, "JPEG", **parametros)


CONVERSION = Conversion(id="heic_a_jpg", extensiones_entrada=(".heic", ".heif"),
                        extension_salida=".jpg", convertir=convertir)
