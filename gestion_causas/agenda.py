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


def dias_habiles_entre(desde, hasta, ruta_feriados: Path = RUTA_FERIADOS_DEFAULT) -> int:
    """Cuenta los días hábiles estrictamente entre `desde` y `hasta` (sin
    incluir `desde`, incluyendo `hasta` si es hábil) — es decir, cuántos días
    hábiles han transcurrido desde `desde` hasta `hasta`. Si `hasta` es
    anterior o igual a `desde`, devuelve 0.

    Ej.: dias_habiles_entre("2026-07-28", "2026-08-03") == 4 (caso real de la
    causa Yáñez con SSLL, O-348-2026: Nico pidió documentos un martes y no
    tuvo respuesta; insistió el lunes siguiente, exactamente 4 días hábiles
    después)."""
    feriados = cargar_feriados(ruta_feriados)
    fecha_desde = _parsear_fecha(desde)
    fecha_hasta = _parsear_fecha(hasta)
    if fecha_hasta <= fecha_desde:
        return 0
    dias = 0
    fecha = fecha_desde
    while fecha < fecha_hasta:
        fecha += timedelta(days=1)
        if es_dia_habil(fecha, feriados):
            dias += 1
    return dias
