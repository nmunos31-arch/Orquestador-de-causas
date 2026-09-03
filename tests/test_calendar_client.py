"""
Tests de calendar_client.py: garantía de solo-lectura y parseo de eventos de
la API de Calendar, sin red (servicio simulado con stubs).
"""

import inspect
import json
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


class TestCacheEventos:
    def test_guardar_cache_eventos_escribe_archivo_con_total_correcto(self, tmp_path):
        servicio = _ServicioCalendarFalso([
            {"items": [
                _evento("Audiencia Unica M-643-2026 Iturriaga con Rendic", date_time="2026-08-21T10:40:00-04:00"),
                _evento("Reunion equipo semanal", date_time="2026-08-25T09:00:00-04:00"),
            ]},
        ])
        ruta = tmp_path / "cache.json"

        resultado = calendar_client.guardar_cache_eventos(ruta=ruta, servicio=servicio)

        assert resultado["total"] == 2
        assert resultado["ruta"] == str(ruta)
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        # El cache declara qué rango cubre, para que un consumidor que necesita
        # otro rango lo sepa en vez de recibir un resultado parcial.
        assert contenido["desde"] == resultado["desde"] == str(date.today())
        assert contenido["hasta"] == resultado["hasta"]
        assert len(contenido["eventos"]) == 2
        assert contenido["eventos"][0] == {
            "fecha": "2026-08-21", "resumen": "Audiencia Unica M-643-2026 Iturriaga con Rendic",
        }
        assert "generado_en" in contenido

    def test_buscar_audiencia_por_rit_desde_cache_filtra_por_rit(self, tmp_path):
        ruta = tmp_path / "cache.json"
        ruta.write_text(json.dumps({
            "generado_en": "2026-08-28T09:00:00",
            "eventos": [
                {"fecha": "2026-08-21", "resumen": "Audiencia Unica M-643-2026 Iturriaga con Rendic"},
                {"fecha": "2026-08-25", "resumen": "Reunion equipo semanal"},
            ],
        }), encoding="utf-8")

        encontrados = calendar_client.buscar_audiencia_por_rit_desde_cache("M-643-2026", ruta=ruta)

        assert len(encontrados) == 1
        assert encontrados[0]["fecha"] == date(2026, 8, 21)

    def test_buscar_audiencia_por_rit_desde_cache_falla_si_no_existe_el_archivo(self, tmp_path):
        import pytest

        ruta = tmp_path / "no-existe.json"
        with pytest.raises(FileNotFoundError):
            calendar_client.buscar_audiencia_por_rit_desde_cache("M-1-2026", ruta=ruta)


class TestDetectarEmpresa:
    def test_reconoce_cada_empresa_por_alias(self):
        assert calendar_client.detectar_empresa("Audiencia Rendic Hermanos") == "Rendic Hermanos"
        assert calendar_client.detectar_empresa('Audiencia única "Rebolledo con Salcobrand" M-637-2026') == "Salcobrand"
        assert calendar_client.detectar_empresa("causa contra Súper 10 S.A.") == "Super 10"

    def test_ignora_mayusculas_y_tildes(self):
        assert calendar_client.detectar_empresa("AUDIENCIA UNICA SALCOBRAND") == "Salcobrand"

    def test_devuelve_none_si_no_reconoce_ninguna(self):
        assert calendar_client.detectar_empresa("Reunión equipo semanal") is None


class TestEventosEmpresasInteres:
    def test_filtra_y_agrega_empresa_y_rit_detectados(self):
        servicio = _ServicioCalendarFalso([
            {"items": [
                _evento('Audiencia única "Rebolledo con Salcobrand" M-637-2026', fecha="2026-08-24"),
                _evento("Reunion equipo semanal", fecha="2026-08-25"),
            ]},
        ])
        eventos = calendar_client.eventos_empresas_interes(date(2026, 8, 1), date(2026, 8, 31), servicio=servicio)
        assert len(eventos) == 1
        assert eventos[0]["empresa_detectada"] == "Salcobrand"
        assert eventos[0]["rit_detectado"] == "M-637-2026"

    def test_rit_detectado_es_none_si_el_titulo_no_trae_rit(self):
        servicio = _ServicioCalendarFalso([
            {"items": [_evento("Audiencia Alvi sin RIT en el título", fecha="2026-08-24")]},
        ])
        eventos = calendar_client.eventos_empresas_interes(date(2026, 8, 1), date(2026, 8, 31), servicio=servicio)
        assert eventos[0]["empresa_detectada"] == "Alvi"
        assert eventos[0]["rit_detectado"] is None

    def test_excluye_causas_con_rit_i_de_inspeccion_del_trabajo(self):
        servicio = _ServicioCalendarFalso([
            {"items": [
                _evento('Audiencia única "Salcobrand S.A. con IPT Curico" I-38-2026', fecha="2026-09-15"),
                _evento('Audiencia única "Rebolledo con Salcobrand" M-637-2026', fecha="2026-08-24"),
            ]},
        ])
        eventos = calendar_client.eventos_empresas_interes(date(2026, 8, 1), date(2026, 9, 30), servicio=servicio)
        assert len(eventos) == 1
        assert eventos[0]["rit_detectado"] == "M-637-2026"


class TestEventosEmpresasInteresDesdeCache:
    """Fase 0 (calendario) reusa el mismo cache que dejó contexto-corrida, en
    vez de hacer su propia llamada a la API sobre un rango ya contenido en él."""

    CACHE = {
        "generado_en": "2026-09-01T09:00:00",
        "desde": "2026-09-01",
        "hasta": "2026-12-01",
        "eventos": [
            {"fecha": "2026-09-15", "resumen": 'Audiencia única "Rebolledo con Salcobrand" M-637-2026'},
            {"fecha": "2026-09-16", "resumen": "Reunion equipo semanal"},
            {"fecha": "2026-09-17", "resumen": 'Audiencia única "Salcobrand S.A. con IPT Curico" I-38-2026'},
        ],
    }

    def _escribir(self, tmp_path, contenido=None):
        ruta = tmp_path / "cache.json"
        ruta.write_text(json.dumps(contenido or self.CACHE), encoding="utf-8")
        return ruta

    def test_aplica_el_mismo_criterio_que_la_version_que_llama_a_la_api(self, tmp_path):
        ruta = self._escribir(tmp_path)
        servicio = _ServicioCalendarFalso([
            {"items": [_evento(e["resumen"], fecha=e["fecha"]) for e in self.CACHE["eventos"]]},
        ])

        desde_api = calendar_client.eventos_empresas_interes(
            date(2026, 9, 1), date(2026, 12, 1), servicio=servicio)
        desde_cache = calendar_client.eventos_empresas_interes_desde_cache(
            date(2026, 9, 1), date(2026, 12, 1), ruta=ruta)

        assert desde_cache == desde_api
        assert [e["rit_detectado"] for e in desde_cache] == ["M-637-2026"]

    def test_recorta_al_rango_pedido(self, tmp_path):
        ruta = self._escribir(tmp_path)
        eventos = calendar_client.eventos_empresas_interes_desde_cache(
            date(2026, 9, 1), date(2026, 9, 14), ruta=ruta)
        assert eventos == []

    def test_falla_si_el_cache_no_cubre_el_rango_pedido(self, tmp_path):
        import pytest

        ruta = self._escribir(tmp_path)
        # --dias-atras > 0: el cache arranca hoy, no cubre el pasado.
        with pytest.raises(ValueError, match="no alcanza"):
            calendar_client.eventos_empresas_interes_desde_cache(
                date(2026, 8, 20), date(2026, 12, 1), ruta=ruta)
        # --dias-adelante mayor al del cache.
        with pytest.raises(ValueError, match="no alcanza"):
            calendar_client.eventos_empresas_interes_desde_cache(
                date(2026, 9, 1), date(2027, 1, 1), ruta=ruta)

    def test_falla_si_el_cache_no_declara_su_rango(self, tmp_path):
        import pytest

        viejo = {k: v for k, v in self.CACHE.items() if k not in ("desde", "hasta")}
        ruta = self._escribir(tmp_path, viejo)
        with pytest.raises(ValueError, match="no declara el rango"):
            calendar_client.eventos_empresas_interes_desde_cache(
                date(2026, 9, 1), date(2026, 12, 1), ruta=ruta)

    def test_falla_si_no_existe_el_archivo(self, tmp_path):
        import pytest

        with pytest.raises(FileNotFoundError):
            calendar_client.eventos_empresas_interes_desde_cache(
                date(2026, 9, 1), date(2026, 12, 1), ruta=tmp_path / "no-existe.json")


class TestClasificarTipoAudiencia:
    def test_audiencia_de_juicio(self):
        assert calendar_client.clasificar_tipo_audiencia("Audiencia de Juicio RIT M-643-2026") == "Juicio"

    def test_aud_de_juicio_abreviado(self):
        assert calendar_client.clasificar_tipo_audiencia("Aud. de juicio Iturriaga con Rendic") == "Juicio"

    def test_audiencia_unica(self):
        assert calendar_client.clasificar_tipo_audiencia('Audiencia única "Rebolledo con Salcobrand" M-637-2026') == "Unica"

    def test_aud_unica_abreviado(self):
        assert calendar_client.clasificar_tipo_audiencia("Aud. única M-1-2026") == "Unica"

    def test_audiencia_preparatoria(self):
        assert calendar_client.clasificar_tipo_audiencia("Audiencia preparatoria RIT O-1-2026") == "Preparatoria"

    def test_reunion_preparatoria_es_alias_de_preparatoria(self):
        # Redacción real y mayoritaria en el calendario del tribunal (confirmado
        # 2026-09-01: 16 de 24 audiencias activas la usaban en vez de "audiencia
        # preparatoria").
        assert calendar_client.clasificar_tipo_audiencia('Reunión preparatoria "Tiznado con Salcobrand" M-744-2026') == "Preparatoria"

    def test_titulo_sin_tipo_reconocible_es_ambiguo(self):
        assert calendar_client.clasificar_tipo_audiencia("Reunion con cliente M-1-2026") == "Ambiguo"

    def test_no_confunde_unica_con_juicio(self):
        # "audiencia de juicio" contiene la palabra "audiencia" pero no debe
        # calzar con el chequeo de "unica".
        assert calendar_client.clasificar_tipo_audiencia("Audiencia de Juicio M-1-2026") != "Unica"


class TestEsEventoNoAudiencia:
    # Confirmado 2026-09-03: Nico corrigió que estos títulos no son
    # audiencias (un plazo procesal o una reunión meramente informativa),
    # así que no deben forzarse a Única/Preparatoria/Juicio ni reportarse
    # como "audiencia ambigua".
    def test_vence_plazo_no_es_audiencia(self):
        assert calendar_client.es_evento_no_audiencia("Vence plazo para contestar demanda Obreque con Salcobrand") is True

    def test_reunion_informativa_no_es_audiencia(self):
        assert calendar_client.es_evento_no_audiencia("Reunión informativa Sáez con Preunic") is True

    def test_reunion_preparatoria_si_es_audiencia(self):
        # No confundir con "reunión informativa": "reunión preparatoria" es
        # alias real de la audiencia preparatoria (ver clasificar_tipo_audiencia).
        assert calendar_client.es_evento_no_audiencia('Reunión preparatoria "Tiznado con Salcobrand" M-744-2026') is False

    def test_audiencia_unica_si_es_audiencia(self):
        assert calendar_client.es_evento_no_audiencia("Audiencia Unica M-643-2026") is False


class TestPrimerEventoFuturo:
    def test_se_queda_con_el_mas_proximo_de_hoy_en_adelante(self):
        eventos = [
            {"fecha": date(2026, 8, 1), "resumen": "pasado"},
            {"fecha": date(2026, 9, 10), "resumen": "futuro lejano"},
            {"fecha": date(2026, 9, 5), "resumen": "futuro cercano"},
        ]
        resultado = calendar_client.primer_evento_futuro(eventos, hoy=date(2026, 9, 1))
        assert resultado["resumen"] == "futuro cercano"

    def test_hoy_mismo_cuenta_como_futuro(self):
        eventos = [{"fecha": date(2026, 9, 1), "resumen": "hoy"}]
        resultado = calendar_client.primer_evento_futuro(eventos, hoy=date(2026, 9, 1))
        assert resultado["resumen"] == "hoy"

    def test_todos_pasados_devuelve_none(self):
        eventos = [{"fecha": date(2026, 8, 1), "resumen": "pasado"}]
        assert calendar_client.primer_evento_futuro(eventos, hoy=date(2026, 9, 1)) is None

    def test_lista_vacia_devuelve_none(self):
        assert calendar_client.primer_evento_futuro([], hoy=date(2026, 9, 1)) is None


class TestMapaAudienciasPorRit:
    EVENTOS = [
        {"fecha": date(2026, 9, 10), "resumen": "Audiencia Unica M-643-2026 Iturriaga con Rendic"},
        {"fecha": date(2026, 8, 1), "resumen": "Audiencia de Juicio O-1-2026 pasada"},
        {"fecha": date(2026, 9, 20), "resumen": "Audiencia de Juicio O-1-2026 reprogramada"},
        {"fecha": date(2026, 9, 15), "resumen": "Reunion equipo semanal"},
    ]

    def test_arma_el_mapa_con_fecha_resumen_y_tipo(self):
        mapa = calendar_client.mapa_audiencias_por_rit(
            ["M-643-2026", "O-1-2026"], self.EVENTOS, hoy=date(2026, 9, 1))
        assert mapa["M-643-2026"] == {
            "fecha": "2026-09-10",
            "resumen": "Audiencia Unica M-643-2026 Iturriaga con Rendic",
            "tipo": "Unica",
        }
        assert mapa["O-1-2026"]["fecha"] == "2026-09-20"
        assert mapa["O-1-2026"]["tipo"] == "Juicio"

    def test_rit_sin_audiencia_proxima_no_aparece(self):
        mapa = calendar_client.mapa_audiencias_por_rit(["M-999-2026"], self.EVENTOS, hoy=date(2026, 9, 1))
        assert mapa == {}

    def test_descarta_vence_plazo_y_usa_la_audiencia_real_posterior(self):
        # Confirmado 2026-09-03 con O-809-2026: el evento "vence plazo" no debe
        # taparse la audiencia preparatoria real que viene después.
        eventos = [
            {"fecha": date(2026, 9, 5), "resumen": "Vence plazo para contestar demanda O-809-2026"},
            {"fecha": date(2026, 9, 20), "resumen": "Audiencia Preparatoria O-809-2026"},
        ]
        mapa = calendar_client.mapa_audiencias_por_rit(["O-809-2026"], eventos, hoy=date(2026, 9, 3))
        assert mapa["O-809-2026"]["fecha"] == "2026-09-20"
        assert mapa["O-809-2026"]["tipo"] == "Preparatoria"

    def test_rit_solo_con_vence_plazo_no_aparece_en_el_mapa(self):
        # Sin ninguna audiencia real todavía, el RIT se salta igual que si no
        # tuviera ningún evento — no se reporta como "audiencia ambigua".
        eventos = [{"fecha": date(2026, 9, 5), "resumen": "Vence plazo para contestar demanda T-995-2026"}]
        mapa = calendar_client.mapa_audiencias_por_rit(["T-995-2026"], eventos, hoy=date(2026, 9, 3))
        assert mapa == {}


class TestLoginNoInteractivo:
    """En una corrida desatendida (contexto-corrida) el flujo de OAuth abre un
    navegador y nunca vuelve. Con permitir_login=False se falla rápido en vez
    de colgar la tarea programada."""

    def test_sin_token_valido_levanta_en_vez_de_abrir_el_navegador(self, tmp_path, monkeypatch):
        import pytest

        monkeypatch.setattr(calendar_client, "TOKEN_PATH", str(tmp_path / "no-existe.json"))
        with pytest.raises(RuntimeError, match="diagnostico-calendario"):
            calendar_client.obtener_credenciales(permitir_login=False)
