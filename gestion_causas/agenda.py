#!/usr/bin/env python3
"""
Feriados chilenos y aritmética de días hábiles/corridos, para la Fase 4
(agenda): calcular cuándo redactar el borrador de ofrecimiento (14 días
corridos antes de la audiencia) y cuándo correr /minuta-laboral (4 días
hábiles antes).
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

RUTA_FERIADOS_DEFAULT = Path(__file__).parent / "feriados.json"


def _parsear_fecha(valor) -> date:
    if isinstance(valor, date):
        return valor
    return datetime.strptime(str(valor), "%Y-%m-%d").date()


def cargar_feriados(ruta: Path = RUTA_FERIADOS_DEFAULT) -> set:
    """Devuelve el conjunto de fechas feriadas (objetos date) de todos los
    años presentes en el archivo."""
    with open(ruta, "r", encoding="utf-8") as f:
        datos = json.load(f)
    feriados = set()
    for anio, fechas in datos.items():
        if anio.startswith("_"):
            continue
        for f_str in fechas:
            feriados.add(_parsear_fecha(f_str))
    return feriados


def es_dia_habil(fecha, feriados: set) -> bool:
    """Hábil = no es sábado, no es domingo, no es feriado."""
    fecha = _parsear_fecha(fecha)
    return fecha.weekday() < 5 and fecha not in feriados


def dias_habiles_antes(fecha_objetivo, n: int, ruta_feriados: Path = RUTA_FERIADOS_DEFAULT) -> date:
    """Cuenta `n` días hábiles hacia atrás desde `fecha_objetivo` (sin incluir
    `fecha_objetivo` mismo) y devuelve esa fecha. Salta sábados, domingos y
    feriados de `ruta_feriados`.

    Ej.: si la audiencia es un martes y no hay feriados de por medio, 4 días
    hábiles antes cae el miércoles de la semana anterior (se saltan sábado y
    domingo).
    """
    feriados = cargar_feriados(ruta_feriados)
    fecha = _parsear_fecha(fecha_objetivo)
    restantes = n
    while restantes > 0:
        fecha -= timedelta(days=1)
        if es_dia_habil(fecha, feriados):
            restantes -= 1
    return fecha


def dias_corridos_antes(fecha_objetivo, n: int) -> date:
    """Resta `n` días corridos (sin excluir fines de semana ni feriados) a
    `fecha_objetivo`. Usado para el hito de "14 días corridos antes de la
    audiencia" del borrador de ofrecimiento."""
    return _parsear_fecha(fecha_objetivo) - timedelta(days=n)
