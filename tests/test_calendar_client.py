"""
Tests de calendar_client.py: garantía de solo-lectura y parseo de eventos de
la API de Calendar, sin red (servicio simulado con stubs).
"""

import inspect
from datetime import date

from gestion_causas import calendar_client


class TestSoloLectura:
    def test_scope_es_unicamente_readonly(self):
        assert calendar_client.SCOPES == ["https://www.googleapis.com/auth/calendar.readonly"]

    def test_no_hay_funciones_de_escritura(self):
        nombres = [n for n, _ in inspect.getmembers(calendar_client, inspect.isfunction)]
        prohibidos = {"crear", "create", "insertar", "insert", "borrar", "eliminar", "delete", "actualizar", "update", "modificar", "modify"}
        for nombre in nombres:
            partes = set(nombre.lower().replace("_", " ").split())
            assert not (partes & prohibidos), f"Función sospechosa de escritura: {nombre}"

    def test_codigo_fuente_no_llama_a_insert_update_ni_delete(self):
        fuente = inspect.getsource(calendar_client)
        assert ".insert(" not in fuente
        assert ".update(" not in fuente
        assert ".delete(" not in fuente
        assert ".patch(" not in fuente


class _EventsFalso:
    """Stub mínimo que imita servicio.events().list().execute() encadenado,
    con paginación opcional."""

    def __init__(self, paginas: list[dict]):
        self._paginas = paginas
        self._indice = 0

    def list(self, calendarId, timeMin, timeMax, singleEvents, orderBy, pageToken=None):
        pagina = self._paginas[self._indice]
        self._indice += 1
        return _Ejecutable(pagina)


class _ServicioCalendarFalso:
    def __init__(self, paginas: list[dict]):
        self._events = _EventsFalso(paginas)

    def events(self):
        return self._events


class _Ejecutable:
    def __init__(self, valor):
        self._valor = valor

    def execute(self):
        return self._valor


def _evento(summary, fecha=None, date_time=None):
    inicio = {"date": fecha} if fecha else {"dateTime": date_time}
    return {"summary": summary, "start": inicio}


class TestListarEventos:
    def test_extrae_fecha_de_dateTime(self):
        servicio = _ServicioCalendarFalso([
            {"items": [_evento("Audiencia Unica M-643-2026 Iturriaga", date_time="2026-08-21T10:40:00-04:00")]},
        ])
        eventos = calendar_client.listar_eventos(date(2026, 8, 1), date(2026, 8, 31), servicio=servicio)
        assert eventos == [{"fecha": date(2026, 8, 21), "resumen": "Audiencia Unica M-643-2026 Iturriaga"}]

    def test_extrae_fecha_de_evento_de_todo_el_dia(self):
        servicio = _ServicioCalendarFalso([
            {"items": [_evento("Vence plazo contestacion O-1411-2026", fecha="2026-09-18")]},
        ])
        eventos = calendar_client.listar_eventos(date(2026, 9, 1), date(2026, 9, 30), servicio=servicio)
        assert eventos[0]["fecha"] == date(2026, 9, 18)

    def test_ignora_eventos_sin_titulo(self):
        servicio = _ServicioCalendarFalso([
            {"items": [{"start": {"date": "2026-09-18"}}]},
        ])
        assert calendar_client.listar_eventos(date(2026, 9, 1), date(2026, 9, 30), servicio=servicio) == []

    def test_pagina_hasta_agotar_next_page_token(self):
        servicio = _ServicioCalendarFalso([
            {"items": [_evento("Evento 1", fecha="2026-09-01")], "nextPageToken": "tok"},
            {"items": [_evento("Evento 2", fecha="2026-09-02")]},
        ])
        eventos = calendar_client.listar_eventos(date(2026, 9, 1), date(2026, 9, 30), servicio=servicio)
        assert len(eventos) == 2


class TestBuscarAudienciaPorRit:
    def test_filtra_por_rit_sobre_eventos_de_la_api(self):
        servicio = _ServicioCalendarFalso([
            {"items": [
                _evento("Audiencia Unica M-643-2026 Iturriaga con Rendic", date_time="2026-08-21T10:40:00-04:00"),
                _evento("Reunion equipo semanal", date_time="2026-08-25T09:00:00-04:00"),
            ]},
        ])
        encontrados = calendar_client.buscar_audiencia_por_rit("M-643-2026", servicio=servicio)
        assert len(encontrados) == 1
        assert encontrados[0]["fecha"] == date(2026, 8, 21)
