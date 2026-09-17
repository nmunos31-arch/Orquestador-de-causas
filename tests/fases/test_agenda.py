import json
from pathlib import Path

from gestion_causas import registro as registro_mod
from gestion_causas.fases import agenda


def _registrar_causa_activa(tmp_path, rit="M-1-2026", **extra):
    ruta_registro = tmp_path / "registro_causas.json"
    datos = {
        "empresa": "Alvi", "demandante": "Perez", "carpeta": str(tmp_path / "Perez con Alvi"),
        "thread_id": "thread-original-1", **extra,
    }
    registro_mod.registrar_causa(rit, datos, ruta=ruta_registro)
    return ruta_registro


def _mapa_audiencias(tmp_path, rit_a_audiencia):
    ruta = tmp_path / "mapa_audiencias.json"
    ruta.write_text(json.dumps({"rit_a_audiencia": rit_a_audiencia}), encoding="utf-8")
    return ruta


def _correr_agenda(contexto, tmp_path, **kwargs):
    kwargs.setdefault("ruta_registro_causas", tmp_path / "registro_causas.json")
    return agenda.correr(contexto, **kwargs)


class TestCorrerSinCausasActivas:
    def test_devuelve_resumen_sin_novedades(self, tmp_path):
        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")}}
        resumen = _correr_agenda(contexto, tmp_path)

        assert resumen == {
            "fase": "agenda",
            "titular": "Sin causas activas para revisar agenda",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }


class TestResolucionDeAudiencia:
    def test_causa_sin_evento_en_el_mapa_se_cuenta_como_sin_evento(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {})

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path)

        metrica = next(m for m in resumen["metricas"] if m["etiqueta"] == "Sin evento de calendario todavía")
        assert metrica["valor"] == 1
        assert resumen["items"] == []
        assert resumen["acciones"] == []

    def test_causa_con_tipo_ambiguo_se_anota_en_notas_y_no_genera_nada(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Reunión rara", "tipo": "Ambiguo"},
        })

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path)

        assert len(resumen["notas"]) == 1
        assert "M-1-2026" in resumen["notas"][0]["detalle"]
        assert resumen["items"] == []

    def test_metricas_incluyen_causas_revisadas_y_borradores_creados(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {})

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path)

        etiquetas = [m["etiqueta"] for m in resumen["metricas"]]
        assert etiquetas == ["Causas revisadas", "Borradores de ofrecimiento creados", "Sin evento de calendario todavía"]


class TestDebeGenerarOfrecimiento:
    AUDIENCIA_UNICA = {"fecha": "2026-10-15", "resumen": "Audiencia única", "tipo": "Única"}
    AUDIENCIA_JUICIO = {"fecha": "2026-10-15", "resumen": "Audiencia de juicio", "tipo": "Juicio"}
    AUDIENCIA_PREPARATORIA = {"fecha": "2026-10-15", "resumen": "Audiencia preparatoria", "tipo": "Preparatoria"}

    def test_true_cuando_tipo_unica_y_hito_ya_paso(self):
        assert agenda._debe_generar_ofrecimiento({}, self.AUDIENCIA_UNICA, "2026-10-02") is True

    def test_true_cuando_tipo_juicio_y_hoy_es_exactamente_el_hito(self):
        assert agenda._debe_generar_ofrecimiento({}, self.AUDIENCIA_JUICIO, "2026-10-01") is True

    def test_false_cuando_tipo_preparatoria(self):
        assert agenda._debe_generar_ofrecimiento({}, self.AUDIENCIA_PREPARATORIA, "2026-10-15") is False

    def test_false_cuando_todavia_no_llega_el_hito(self):
        assert agenda._debe_generar_ofrecimiento({}, self.AUDIENCIA_UNICA, "2026-09-30") is False

    def test_false_cuando_causa_marca_aplica_ofrecimiento_false(self):
        causa = {"aplica_ofrecimiento": False}
        assert agenda._debe_generar_ofrecimiento(causa, self.AUDIENCIA_UNICA, "2026-10-02") is False

    def test_false_cuando_ya_tiene_oferta_borrador_creado(self):
        causa = {"oferta_borrador_creado": True}
        assert agenda._debe_generar_ofrecimiento(causa, self.AUDIENCIA_UNICA, "2026-10-02") is False


class TestEvaluarMontosOfrecimiento:
    def test_pasa_ruta_archivo_y_texto_del_cuadro_a_reasoning(self, tmp_path, monkeypatch):
        ruta_demanda = tmp_path / "demanda.pdf"
        llamadas = []

        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None):
            llamadas.append((tarea, contexto, schema, ruta_archivo))
            return {
                "demandantes": [{"apellido": "Pérez", "monto_recargo_30": 500000, "monto_afc": 200000}],
                "hay_discrepancia": False,
                "detalle_discrepancia": "",
            }

        monkeypatch.setattr(agenda.reasoning, "preguntar", preguntar_falso)

        resultado = agenda._evaluar_montos_ofrecimiento("Conceptos demandados: Recargo 30%, AFC", ruta_demanda)

        assert resultado["demandantes"][0]["apellido"] == "Pérez"
        tarea, contexto, schema, ruta_archivo = llamadas[0]
        assert contexto == {"texto_cuadro_original": "Conceptos demandados: Recargo 30%, AFC"}
        assert schema == agenda.SCHEMA_OFRECIMIENTO
        assert ruta_archivo == ruta_demanda

    def test_propaga_el_error_de_reasoning_sin_modificarlo(self, tmp_path, monkeypatch):
        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None):
            return {"error": "Claude no devolvió JSON válido"}

        monkeypatch.setattr(agenda.reasoning, "preguntar", preguntar_falso)

        resultado = agenda._evaluar_montos_ofrecimiento("texto", tmp_path / "demanda.pdf")

        assert resultado == {"error": "Claude no devolvió JSON válido"}


class TestArmarCuerpoOfrecimiento:
    def test_un_solo_demandante_audiencia_unica(self):
        demandantes = [{"apellido": "Pérez", "monto_recargo_30": 500000, "monto_afc": 200000}]

        cuerpo = agenda._armar_cuerpo_ofrecimiento(demandantes, "Única", "2026-10-15", 14)

        assert cuerpo == (
            "Estimado Román:\n\n"
            "En esta causa, con audiencia única fijada para el 15 de octubre de 2026 "
            "(en 14 días), se demanda lo siguiente:\n\n"
            "Pérez:\n"
            "Recargo 30%: $500.000\n"
            "Devolución AFC: $200.000\n"
            "Total: $700.000\n\n"
            "Por lo anterior, consulto si hago un ofrecimiento por $420.000 para don/doña "
            "Pérez, equivalente al 60% del total\n\n\n"
            "Atentamente,"
        )

    def test_dos_demandantes_audiencia_de_juicio(self):
        demandantes = [
            {"apellido": "Pérez", "monto_recargo_30": 500000, "monto_afc": 200000},
            {"apellido": "González", "monto_recargo_30": 300000, "monto_afc": 100000},
        ]

        cuerpo = agenda._armar_cuerpo_ofrecimiento(demandantes, "Juicio", "2026-10-15", 14)

        assert cuerpo == (
            "Estimado Román:\n\n"
            "En esta causa, con audiencia de juicio fijada para el 15 de octubre de 2026 "
            "(en 14 días), se demanda lo siguiente:\n\n"
            "Pérez:\n"
            "Recargo 30%: $500.000\n"
            "Devolución AFC: $200.000\n"
            "Total: $700.000\n\n"
            "González:\n"
            "Recargo 30%: $300.000\n"
            "Devolución AFC: $100.000\n"
            "Total: $400.000\n\n"
            "Total demandado (todos): $1.100.000\n\n"
            "Por lo anterior, consulto si hago un ofrecimiento por $420.000 para don/doña "
            "Pérez y $240.000 para don/doña González, equivalente al 60% del total\n\n\n"
            "Atentamente,"
        )


class TestArmarAsuntoOfrecimiento:
    def test_arma_el_asunto_con_apellido_empresa_y_rit(self):
        causa = {"demandante": "Pérez", "empresa": "Alvi"}

        asunto = agenda._armar_asunto_ofrecimiento(causa, "M-1-2026")

        assert asunto == 'Demanda laboral "Pérez con Alvi" Rit M-1-2026'


class TestProcesarOfrecimientoIntegracion:
    """Prueba _procesar_ofrecimiento (y por lo tanto correr()) de punta a
    punta, mockeando solo gmail_client y reasoning.preguntar — nunca la red
    real."""

    def _causa_lista_para_ofrecimiento(self, tmp_path, **extra):
        carpeta = tmp_path / "Perez con Alvi"
        carpeta.mkdir()
        (carpeta / "demanda.pdf").write_bytes(b"%PDF-1.4 contenido falso")
        return _registrar_causa_activa(tmp_path, carpeta=str(carpeta), **extra)

    def _mock_evaluacion(self, monkeypatch, **overrides):
        resultado = {
            "demandantes": [{"apellido": "Pérez", "monto_recargo_30": 500000, "monto_afc": 200000}],
            "hay_discrepancia": False,
            "detalle_discrepancia": "",
        }
        resultado.update(overrides)
        monkeypatch.setattr(agenda.reasoning, "preguntar", lambda *a, **k: resultado)

    def test_responde_dentro_de_la_cadena_interna_si_existe(self, tmp_path, monkeypatch):
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch)

        monkeypatch.setattr(
            agenda.gmail_client, "buscar_hilos",
            lambda query, **k: [{"id": "thread-interno"}] if "gomezyriesco.cl" in query else [],
        )
        monkeypatch.setattr(
            agenda.gmail_client, "leer_hilo",
            lambda thread_id, **k: [
                {"sender": "Cristina Gil <cgil@gomezyriesco.cl>", "cuerpo_texto": "Cuadro original", "subject": "Demanda laboral \"Perez con Alvi\" M-1-2026"},
                {"sender": "Nico Muñoz <nmunoz@gomezyriesco.cl>", "cuerpo_texto": "ok", "subject": "Re: ..."},
            ],
        )
        monkeypatch.setattr(agenda.gmail_client, "listar_borradores_de_hilo", lambda thread_id, **k: [])

        llamadas_crear = []
        monkeypatch.setattr(
            agenda.gmail_client, "crear_borrador",
            lambda destinatario, asunto, cuerpo, **k: llamadas_crear.append((destinatario, asunto, cuerpo, k)) or {"id": "draft-1"},
        )

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert len(llamadas_crear) == 1
        destinatario, asunto, cuerpo, kwargs = llamadas_crear[0]
        assert destinatario == "cgil@gomezyriesco.cl"
        assert kwargs["thread_id"] == "thread-interno"
        assert asunto.startswith("Re: ")

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["oferta_borrador_creado"] is True
        assert resumen["metricas"][1] == {"etiqueta": "Borradores de ofrecimiento creados", "valor": 1}
        assert resumen["items"] == [{"rit": "M-1-2026", "titulo": "Perez con Alvi", "detalle": "Borrador de ofrecimiento creado"}]

    def test_crea_correo_nuevo_si_no_encuentra_la_cadena_interna(self, tmp_path, monkeypatch):
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch)

        monkeypatch.setattr(agenda.gmail_client, "buscar_hilos", lambda query, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "buscar_borrador_por_asunto", lambda fragmento, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "leer_hilo", lambda thread_id, **k: [])

        llamadas_crear = []
        monkeypatch.setattr(
            agenda.gmail_client, "crear_borrador",
            lambda destinatario, asunto, cuerpo, **k: llamadas_crear.append((destinatario, asunto, cuerpo, k)) or {"id": "draft-2"},
        )

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert len(llamadas_crear) == 1
        destinatario, asunto, cuerpo, kwargs = llamadas_crear[0]
        assert destinatario == "rgomez@gomezyriesco.cl"
        assert kwargs.get("thread_id") is None
        assert asunto == 'Demanda laboral "Perez con Alvi" Rit M-1-2026'

    def test_no_duplica_si_ya_existe_un_borrador_en_la_cadena(self, tmp_path, monkeypatch):
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch)

        monkeypatch.setattr(agenda.gmail_client, "buscar_hilos", lambda query, **k: [{"id": "thread-interno"}])
        monkeypatch.setattr(
            agenda.gmail_client, "leer_hilo",
            lambda thread_id, **k: [{"sender": "cgil@gomezyriesco.cl", "cuerpo_texto": "x", "subject": "x"}],
        )
        monkeypatch.setattr(agenda.gmail_client, "listar_borradores_de_hilo", lambda thread_id, **k: [{"id": "draft-existente"}])

        llamadas_crear = []
        monkeypatch.setattr(agenda.gmail_client, "crear_borrador", lambda *a, **k: llamadas_crear.append(1))

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert llamadas_crear == []
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["oferta_borrador_creado"] is True

    def test_anota_accion_si_no_hay_demanda_pdf_en_la_carpeta(self, tmp_path, monkeypatch):
        carpeta = tmp_path / "Perez con Alvi"
        carpeta.mkdir()
        ruta_registro = _registrar_causa_activa(tmp_path, carpeta=str(carpeta))
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert len(resumen["acciones"]) == 1
        assert "demanda.pdf" in resumen["acciones"][0]["que"]
        assert resumen["acciones"][0]["urgencia"] == "media"

    def test_anota_accion_de_urgencia_alta_si_hay_discrepancia(self, tmp_path, monkeypatch):
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch, hay_discrepancia=True, detalle_discrepancia="Demanda dice $500.000, cuadro decía $400.000")

        monkeypatch.setattr(agenda.gmail_client, "buscar_hilos", lambda query, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "buscar_borrador_por_asunto", lambda fragmento, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "leer_hilo", lambda thread_id, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-3"})

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        accion_discrepancia = next(a for a in resumen["acciones"] if "Discrepancia" in a["que"])
        assert accion_discrepancia["urgencia"] == "alta"
        assert "500.000" in accion_discrepancia["que"]
