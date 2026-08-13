#!/usr/bin/env python3
"""
Parseo de archivos .ics (exportados a mano del calendario de
nmunoz@gomezyriesco.cl vía navegador) para la Fase 4 (agenda).

Existe porque el conector de Calendar de Claude solo tiene permiso
`freeBusyReader` sobre esa cuenta — puede ver cuándo Nico está ocupado, pero
no el título de los eventos, así que no sirve para encontrar la fecha ni el
tipo de una audiencia por RIT. El mecanismo de exportar el .ics por
navegador ya existía (lo usa la tarea `revision-semanal-calendario-audiencias`)
y sí trae el contenido completo.
"""

import re
from datetime import date, datetime
from pathlib import Path

from .registro import normalizar_rit

_PATRON_FOLD = re.compile(r"\r?\n[ \t]")
_PATRON_FECHA = re.compile(r"DTSTART[^:]*:(\d{8})")
_PATRON_SUMMARY = re.compile(r"^SUMMARY:(.*)$", re.MULTILINE)


def _desdoblar_lineas(texto: str) -> str:
    """Une las líneas "plegadas" del formato iCalendar (una línea larga que
    el estándar corta agregando un espacio/tab al inicio de la continuación)."""
    return _PATRON_FOLD.sub("", texto)


def _desescapar(valor: str) -> str:
    return valor.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip()


def parsear_eventos(ruta_ics) -> list:
    """Lee un .ics y devuelve una lista de {"fecha": date, "resumen": str},
    uno por VEVENT que tenga DTSTART y SUMMARY. Eventos sin esos dos campos
    se omiten (no deberían aparecer en un .ics bien formado, pero por si
    acaso)."""
    texto = Path(ruta_ics).read_text(encoding="utf-8", errors="replace")
    texto = _desdoblar_lineas(texto)

    eventos = []
    for bloque in texto.split("BEGIN:VEVENT")[1:]:
        bloque = bloque.split("END:VEVENT")[0]

        m_fecha = _PATRON_FECHA.search(bloque)
        m_resumen = _PATRON_SUMMARY.search(bloque)
        if not m_fecha or not m_resumen:
            continue

        fecha = datetime.strptime(m_fecha.group(1), "%Y%m%d").date()
        resumen = _desescapar(m_resumen.group(1))
        eventos.append({"fecha": fecha, "resumen": resumen})

    return eventos


def buscar_eventos_por_rit(eventos: list, rit: str) -> list:
    """Filtra `eventos` (de parsear_eventos) a los que mencionan `rit` en el
    resumen — comparación por substring sobre el RIT normalizado (sin
    espacios, guiones equivalentes, insensible a mayúsculas), igual criterio
    que buscar_carpeta_existente_por_rit en carpetas.py."""
    objetivo = normalizar_rit(rit)
    return [e for e in eventos if objetivo in normalizar_rit(e["resumen"])]


def buscar_audiencia_por_rit(ruta_ics, rit: str) -> list:
    """Atajo: parsea el .ics y devuelve directo los eventos que mencionan
    `rit`, ordenados por fecha ascendente (la más próxima primero)."""
    eventos = buscar_eventos_por_rit(parsear_eventos(ruta_ics), rit)
    return sorted(eventos, key=lambda e: e["fecha"])
