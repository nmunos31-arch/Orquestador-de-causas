#!/usr/bin/env python3
"""
Manejo de la carpeta de cada causa dentro de C:\\Users\\usuario\\Documents\\Temporal 2\\Minutas.

Convención de nombre acordada con el usuario: "[Apellido] con [Empresa] [RIT]"
(ej. "Yañez con SSLL O-348-2026"), donde Empresa usa la abreviatura que ya se
usaba a mano en las carpetas existentes (ver `Minutas/Yañez con SSLL`,
`Minutas/Millahueque con Alvi O-394-2026`).
"""

import re
import unicodedata
from pathlib import Path

RUTA_MINUTAS_DEFAULT = Path(r"C:\Users\usuario\Documents\Temporal 2\Minutas")

# Nombre normalizado de la Demandada (sin tildes, minúsculas) -> abreviatura
# usada en el nombre de carpeta. Debe cubrir exactamente las 4 empresas del
# filtro del proyecto (ver empresas.py).
_ABREVIATURA_EMPRESA = {
    "rendic hermanos": "Rendic",
    "rendic hermanos s.a": "Rendic",
    "rendic": "Rendic",
    "alvi": "Alvi",
    "super 10": "Super 10",
    "servicios logisticos santiago": "SSLL",
    "servicios logisticos santiago s.a": "SSLL",
    "ssll": "SSLL",
    "preunic": "Preunic",
    "preunic s.a": "Preunic",
    "salcobrand": "Salcobrand",
    "salcobrand s.a": "Salcobrand",
}

_CARACTERES_ILEGALES_WINDOWS = re.compile(r'[\\/:*?"<>|]')

# Extensiones de imagen que, combinadas con un tamaño chico, se tratan como
# adjuntos de firma/logo del correo y no como prueba documental.
_EXTENSIONES_IMAGEN_FIRMA = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}
_TAMANO_MAXIMO_FIRMA_BYTES = 100 * 1024  # 100 KB


def _sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def abreviar_empresa(nombre_empresa: str) -> str:
    """Convierte el nombre de la Demandada (tal como viene del cuadro del
    correo) a la abreviatura usada en el nombre de carpeta. Si no la
    reconoce, devuelve el nombre tal cual (saneado) — mejor una carpeta con
    el nombre completo que una carpeta que no se crea."""
    clave = _sin_tildes(nombre_empresa).strip().lower().rstrip(".")
    return _ABREVIATURA_EMPRESA.get(clave, nombre_empresa.strip())


def sanear_nombre_windows(nombre: str) -> str:
    """Quita caracteres ilegales en nombres de archivo/carpeta de Windows y
    recorta espacios sobrantes."""
    limpio = _CARACTERES_ILEGALES_WINDOWS.sub("", nombre)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    return limpio.rstrip(".")  # Windows no permite terminar en punto


def nombre_carpeta_causa(apellido_demandante: str, empresa: str, rit: str) -> str:
    """Nombre canónico: '[Apellido] con [Empresa] [RIT]'."""
    empresa_abrev = abreviar_empresa(empresa)
    crudo = f"{apellido_demandante.strip()} con {empresa_abrev} {rit.strip()}"
    return sanear_nombre_windows(crudo)


def ruta_carpeta_causa(
    apellido_demandante: str, empresa: str, rit: str, base: Path = RUTA_MINUTAS_DEFAULT
) -> Path:
    return base / nombre_carpeta_causa(apellido_demandante, empresa, rit)


def buscar_carpeta_existente_por_rit(rit: str, base: Path = RUTA_MINUTAS_DEFAULT) -> Path | None:
    """Busca una carpeta ya existente para este RIT, para no duplicar
    carpetas de causas que ya se trabajaron a mano ANTES de que existiera
    esta automatización.

    La mayoría de las carpetas viejas NO tienen el RIT en su propio nombre
    (ej. 'Yañez con SSLL', convención "[Apellido] con [Empresa]"), pero casi
    siempre sí lo tienen en el nombre de alguno de sus archivos (la minuta,
    el "E-Acompaña documentos...", el listado de prueba, etc. — todos se
    nombran con el RIT). Por eso se busca en dos niveles:
    1. En el nombre de la carpeta misma (match directo, más rápido).
    2. Si no hay match, en el nombre de cada archivo dentro de cada carpeta.

    Comparación por substring sobre el RIT normalizado (sin espacios, guiones
    equivalentes, insensible a mayúsculas) — no exige que el nombre completo
    coincida, porque los archivos siempre traen texto alrededor del RIT.

    Devuelve la carpeta existente o None si ninguna la contiene.
    """
    from .registro import normalizar_rit

    if not base.exists():
        return None

    objetivo = normalizar_rit(rit)

    carpetas = [h for h in base.iterdir() if h.is_dir()]
    for carpeta in carpetas:
        if objetivo in normalizar_rit(carpeta.name):
            return carpeta

    for carpeta in carpetas:
        for archivo in carpeta.iterdir():
            if archivo.is_file() and objetivo in normalizar_rit(archivo.name):
                return carpeta
    return None


def crear_carpeta_causa(
    apellido_demandante: str, empresa: str, rit: str, base: Path = RUTA_MINUTAS_DEFAULT
) -> Path:
    """Devuelve la carpeta de la causa, creándola si no existe.

    Antes de crear una carpeta nueva, busca si ya existe una carpeta bajo
    `base` cuyo nombre contenga este RIT (ver buscar_carpeta_existente_por_rit)
    — así una causa que Nico ya armó a mano con otro nombre de carpeta no
    queda duplicada. Si no encuentra ninguna, crea la carpeta con el nombre
    canónico nuevo.
    """
    existente = buscar_carpeta_existente_por_rit(rit, base)
    if existente is not None:
        return existente

    carpeta = ruta_carpeta_causa(apellido_demandante, empresa, rit, base)
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def es_adjunto_firma(nombre_archivo: str, tamano_bytes: int) -> bool:
    """True si el adjunto parece ser una firma/logo del correo (imagen chica)
    y no un documento de prueba. Heurística: extensión de imagen + tamaño
    bajo el umbral. No se filtra por nombre porque varía mucho entre
    firmantes."""
    extension = Path(nombre_archivo).suffix.lower()
    return extension in _EXTENSIONES_IMAGEN_FIRMA and tamano_bytes < _TAMANO_MAXIMO_FIRMA_BYTES


def guardar_adjunto(carpeta: Path, nombre_archivo: str, contenido: bytes) -> dict:
    """Guarda `contenido` como `nombre_archivo` dentro de `carpeta`, sin pisar
    un archivo que ya exista con ese nombre (se asume que si el nombre ya
    está, el documento ya fue guardado en una corrida anterior).

    Devuelve {"ruta": Path, "guardado": bool} — guardado=False si ya existía.
    """
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre_saneado = sanear_nombre_windows(nombre_archivo)
    destino = carpeta / nombre_saneado

    if destino.exists():
        return {"ruta": destino, "guardado": False}

    destino.write_bytes(contenido)
    return {"ruta": destino, "guardado": True}


def copiar_archivo_local(origen: Path, carpeta_destino: Path, nombre_archivo: str) -> dict:
    """Copia un archivo YA EXISTENTE en disco (ej. el EERR de una causa
    anterior del mismo CECO) a la carpeta de otra causa. Mismo criterio de no
    pisar que guardar_adjunto: si el nombre ya existe en destino, no copia.

    Devuelve {"ruta": Path, "copiado": bool}.
    """
    carpeta_destino.mkdir(parents=True, exist_ok=True)
    nombre_saneado = sanear_nombre_windows(nombre_archivo)
    destino = carpeta_destino / nombre_saneado

    if destino.exists():
        return {"ruta": destino, "copiado": False}

    destino.write_bytes(Path(origen).read_bytes())
    return {"ruta": destino, "copiado": True}


_PATRON_EERR = re.compile(r"eerr|estado.?de.?resultado|ifrs", re.IGNORECASE)


def parece_eerr(nombre_archivo: str) -> bool:
    """Heurística de nombre para detectar si un adjunto es el Estado de
    Resultados del local (ej. 'EERR 2026.pdf', 'Ec1223_Rendic_IFRS_individual.pdf').
    Usada en la Fase 3 (goteo) para asociar el documento recibido al CECO de
    la causa, sin depender de que el usuario lo confirme a mano."""
    return bool(_PATRON_EERR.search(nombre_archivo))


def listar_archivos_carpeta(carpeta: Path) -> list:
    """Nombres de los archivos (no subcarpetas) que ya existen en `carpeta`.
    Usado en la Fase 3 para saber qué adjuntos del hilo todavía no se han
    guardado, sin depender de volver a intentar guardar_adjunto uno por uno
    (aunque esa también es idempotente)."""
    if not carpeta.exists():
        return []
    return sorted(f.name for f in carpeta.iterdir() if f.is_file())
