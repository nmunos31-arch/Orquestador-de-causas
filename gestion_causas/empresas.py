"""Normalización de nombre de empresa contra la lista cerrada de las 6
empresas del proyecto (ver subagentes/smu.md paso 2d). Independiente de
`carpetas._ABREVIATURA_EMPRESA` (esa tabla da la abreviatura de carpeta, no
valida si el nombre es una de las 6)."""

from __future__ import annotations

import unicodedata

EMPRESAS_VALIDAS = (
    "Rendic Hermanos",
    "Alvi",
    "Super 10",
    "Servicios Logísticos Santiago",
    "Preunic",
    "Salcobrand",
)


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sin_tildes.lower().replace("s.a.", "").replace("s.a", "").strip()


def normalizar_empresa(nombre: str | None) -> str | None:
    """Devuelve el nombre canónico (una de `EMPRESAS_VALIDAS`) si `nombre`
    coincide con alguna (sin importar mayúsculas, tildes, o el sufijo
    "S.A."/"S.A"), o None si no coincide con ninguna."""
    if not nombre:
        return None
    objetivo = _normalizar(nombre)
    for empresa in EMPRESAS_VALIDAS:
        if _normalizar(empresa) == objetivo:
            return empresa
    return None
