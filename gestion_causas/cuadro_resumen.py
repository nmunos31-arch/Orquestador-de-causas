"""Extracción de los campos de una sola línea del cuadro-resumen que llega
en el correo de una demanda nueva (ver subagentes/smu.md paso 2c y
docs/2026-07-07-informe-juicios-email-design.md). Solo extrae los campos que
son "Etiqueta: valor" en una línea — "Hechos" y "Conceptos demandados" son
texto libre/multilínea y se dejan para que los procese Claude directamente
sobre el cuerpo completo (ver `fases/smu.py::_generar_resumen_narrativo`),
en vez de intentar acotarlos con regex."""

from __future__ import annotations

import re
import unicodedata

CAMPOS_OBLIGATORIOS = ("rit", "tribunal", "cuantia")

# Clave interna -> variantes de etiqueta aceptadas (ya sin tildes, minúsculas).
_ETIQUETAS = {
    "rit": ("rit",),
    "tribunal": ("tribunal",),
    "demandante": ("demandante",),
    "rut": ("rut",),
    "fecha_audiencia": ("fecha audiencia", "fecha de audiencia"),
    "demandada": ("demandada",),
    "cuantia": ("cuantia",),
    "materia": ("materia",),
    "fecha_ingreso_pjud": ("fecha de ingreso al pjud", "fecha ingreso pjud", "fecha ingreso al pjud"),
}

_LINEA_ETIQUETA_VALOR = re.compile(r"^\s*([^:\n]{2,40}?)\s*:\s*(.+?)\s*$")


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).lower()


def extraer_campos_cuadro(cuerpo_texto: str) -> dict:
    """Recorre `cuerpo_texto` línea por línea buscando "Etiqueta: valor".
    Devuelve un dict solo con las claves que encontró (nunca claves con
    valor vacío) — un campo ausente simplemente no aparece."""
    campos: dict = {}
    for linea in cuerpo_texto.splitlines():
        coincidencia = _LINEA_ETIQUETA_VALOR.match(linea)
        if not coincidencia:
            continue
        etiqueta_cruda = _sin_tildes(coincidencia.group(1).strip())
        valor = coincidencia.group(2).strip()
        if not valor:
            continue
        for clave, variantes in _ETIQUETAS.items():
            if clave in campos:
                continue
            if etiqueta_cruda in variantes:
                campos[clave] = valor
                break
    return campos


def cuadro_completo(campos: dict) -> bool:
    """True si `campos` trae los 3 campos sin los que no vale la pena seguir
    (ver docs/2026-07-07-informe-juicios-email-design.md, "Manejo de
    errores")."""
    return all(campos.get(clave) for clave in CAMPOS_OBLIGATORIOS)
