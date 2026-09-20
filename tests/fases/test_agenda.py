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
        assert etiquetas == [
            "Causas revisadas", "Borradores de ofrecimiento creados",
            "Minutas generadas", "Sin evento de calendario todavía",
        ]


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

    def test_false_cuando_causa_ya_tiene_estado_acuerdo(self):
        causa = {"estado_acuerdo": "pendiente_pago"}
        assert agenda._debe_generar_ofrecimiento(causa, self.AUDIENCIA_UNICA, "2026-10-02") is False

    def test_false_cuando_estado_acuerdo_es_otro_valor_no_vacio(self):
        # El punto es "hay un proceso de acuerdo en curso", no una lista
        # cerrada de estados conocidos.
        causa = {"estado_acuerdo": "acuerdo_verbal"}
        assert agenda._debe_generar_ofrecimiento(causa, self.AUDIENCIA_UNICA, "2026-10-02") is False


class TestDebeGenerarMinuta:
    AUDIENCIA_UNICA = {"fecha": "2026-10-15", "resumen": "Audiencia única", "tipo": "Única"}
    AUDIENCIA_PREPARATORIA = {"fecha": "2026-10-15", "resumen": "Audiencia preparatoria", "tipo": "Preparatoria"}
    AUDIENCIA_JUICIO = {"fecha": "2026-10-15", "resumen": "Audiencia de juicio", "tipo": "Juicio"}

    def test_true_cuando_tipo_unica_y_hito_ya_paso(self):
        assert agenda._debe_generar_minuta({}, self.AUDIENCIA_UNICA, "2026-10-14") is True

    def test_true_cuando_tipo_preparatoria(self):
        assert agenda._debe_generar_minuta({}, self.AUDIENCIA_PREPARATORIA, "2026-10-14") is True

    def test_false_cuando_tipo_juicio(self):
        assert agenda._debe_generar_minuta({}, self.AUDIENCIA_JUICIO, "2026-10-14") is False

    def test_false_cuando_todavia_no_llega_el_hito(self):
        assert agenda._debe_generar_minuta({}, self.AUDIENCIA_UNICA, "2026-10-01") is False

    def test_false_cuando_causa_marca_aplica_minuta_laboral_false(self):
        causa = {"aplica_minuta_laboral": False}
        assert agenda._debe_generar_minuta(causa, self.AUDIENCIA_UNICA, "2026-10-14") is False

    def test_false_cuando_ya_tiene_minuta_ejecutada(self):
        causa = {"minuta_ejecutada": True}
        assert agenda._debe_generar_minuta(causa, self.AUDIENCIA_UNICA, "2026-10-14") is False

    def test_estado_acuerdo_no_bloquea_la_minuta(self):
        # A diferencia del ofrecimiento, la minuta de prueba sigue
        # generándose aunque haya un acuerdo en curso.
        causa = {"estado_acuerdo": "pendiente_pago"}
        assert agenda._debe_generar_minuta(causa, self.AUDIENCIA_UNICA, "2026-10-14") is True


class TestProcesarMinutaIntegracion:
    def _causa_lista_para_minuta(self, tmp_path, **extra):
        carpeta = tmp_path / "Perez con Alvi"
        carpeta.mkdir()
        return _registrar_causa_activa(tmp_path, carpeta=str(carpeta), **extra), carpeta

    AUDIENCIA_PREPARATORIA = {"fecha": "2026-10-15", "resumen": "Audiencia preparatoria", "tipo": "Preparatoria"}

    def test_marca_minuta_ejecutada_cuando_aparece_un_docx_nuevo(self, tmp_path, monkeypatch):
        ruta_registro, carpeta = self._causa_lista_para_minuta(tmp_path)
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)

        def invocar_falso(prompt, carpeta_arg):
            assert "M-1-2026" in prompt
            (carpeta_arg / "Minuta audiencia preparatoria M-1-2026.docx").write_bytes(b"docx falso")
            return {"ok": True, "salida": ""}

        monkeypatch.setattr(agenda.reasoning, "invocar_skill", invocar_falso)

        acciones: list[dict] = []
        creado = agenda._procesar_minuta(
            {"rit": "M-1-2026", "carpeta": str(carpeta)}, self.AUDIENCIA_PREPARATORIA,
            "2026-10-14", ruta_registro, acciones,
        )

        assert creado is True
        assert acciones == []
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["minuta_ejecutada"] is True

    def test_no_marca_el_flag_si_la_skill_devuelve_error(self, tmp_path, monkeypatch):
        ruta_registro, carpeta = self._causa_lista_para_minuta(tmp_path)

        monkeypatch.setattr(
            agenda.reasoning, "invocar_skill",
            lambda prompt, carpeta_arg: {"error": "timeout"},
        )

        acciones: list[dict] = []
        creado = agenda._procesar_minuta(
            {"rit": "M-1-2026", "carpeta": str(carpeta)}, self.AUDIENCIA_PREPARATORIA,
            "2026-10-14", ruta_registro, acciones,
        )

        assert creado is False
        assert len(acciones) == 1
        assert "timeout" in acciones[0]["que"]
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada.get("minuta_ejecutada") is not True

    def test_no_marca_el_flag_si_no_aparece_ningun_docx_nuevo(self, tmp_path, monkeypatch):
        ruta_registro, carpeta = self._causa_lista_para_minuta(tmp_path)

        monkeypatch.setattr(
            agenda.reasoning, "invocar_skill",
            lambda prompt, carpeta_arg: {"ok": True, "salida": ""},
        )

        acciones: list[dict] = []
        creado = agenda._procesar_minuta(
            {"rit": "M-1-2026", "carpeta": str(carpeta)}, self.AUDIENCIA_PREPARATORIA,
            "2026-10-14", ruta_registro, acciones,
        )

        assert creado is False
        assert len(acciones) == 1
        assert "no se detectó una minuta nueva" in acciones[0]["que"]
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada.get("minuta_ejecutada") is not True

    def test_anota_accion_si_no_existe_la_carpeta(self, tmp_path):
        carpeta_inexistente = tmp_path / "no existe"
        ruta_registro = _registrar_causa_activa(tmp_path, carpeta=str(carpeta_inexistente))

        acciones: list[dict] = []
        creado = agenda._procesar_minuta(
            {"rit": "M-1-2026", "carpeta": str(carpeta_inexistente)}, self.AUDIENCIA_PREPARATORIA,
            "2026-10-14", ruta_registro, acciones,
        )

        assert creado is False
        assert len(acciones) == 1
        assert "no se encontró la carpeta" in acciones[0]["que"]

    def test_no_confunde_un_docx_de_minuta_preexistente_con_uno_nuevo(self, tmp_path, monkeypatch):
        """Si la carpeta ya tenía una minuta de una corrida anterior (re-
        ejecución de la skill) y la skill no la regenera, no debe marcarse
        como recién creada."""
        ruta_registro, carpeta = self._causa_lista_para_minuta(tmp_path)
        (carpeta / "Minuta audiencia preparatoria M-1-2026.docx").write_bytes(b"ya existia")

        monkeypatch.setattr(
            agenda.reasoning, "invocar_skill",
            lambda prompt, carpeta_arg: {"ok": True, "salida": ""},
        )

        acciones: list[dict] = []
        creado = agenda._procesar_minuta(
            {"rit": "M-1-2026", "carpeta": str(carpeta)}, self.AUDIENCIA_PREPARATORIA,
            "2026-10-14", ruta_registro, acciones,
        )

        assert creado is False
        assert len(acciones) == 1


class TestCorrerConAmbosHitosElMismoDia:
    def test_una_causa_puede_disparar_ofrecimiento_y_minuta_el_mismo_dia(self, tmp_path, monkeypatch):
        carpeta = tmp_path / "Perez con Alvi"
        carpeta.mkdir()
        (carpeta / "demanda.pdf").write_bytes(b"%PDF-1.4 contenido falso")
        ruta_registro = _registrar_causa_activa(tmp_path, carpeta=str(carpeta))
        # Única con audiencia el 2026-10-15: hito de 14 días corridos cae el
        # 2026-10-01, hito de 4 días hábiles cae bastante después — se elige
        # una fecha_hoy posterior a ambos para que disparen juntos.
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-15", "resumen": "Audiencia única", "tipo": "Única"},
        })

        monkeypatch.setattr(
            agenda.reasoning, "preguntar",
            lambda *a, **k: {
                "demandantes": [{"apellido": "Pérez", "monto_recargo_30": 500000, "monto_afc": 200000}],
                "hay_discrepancia": False, "detalle_discrepancia": "",
            },
        )

        def invocar_skill_falso(prompt, carpeta_arg):
            (carpeta_arg / "Minuta audiencia única M-1-2026.docx").write_bytes(b"docx falso")
            return {"ok": True, "salida": ""}

        monkeypatch.setattr(agenda.reasoning, "invocar_skill", invocar_skill_falso)
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)
        monkeypatch.setattr(agenda.gmail_client, "buscar_hilos", lambda query, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "buscar_borrador_por_asunto", lambda fragmento, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "leer_hilo", lambda thread_id, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})

        contexto = {"fecha_hoy": "2026-10-10", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert resumen["metricas"][1] == {"etiqueta": "Borradores de ofrecimiento creados", "valor": 1}
        assert resumen["metricas"][2] == {"etiqueta": "Minutas generadas", "valor": 1}
        detalles = {item["detalle"] for item in resumen["items"]}
        assert detalles == {"Borrador de ofrecimiento creado", "Minuta de prueba generada"}
        assert resumen["titular"] == "1 borrador de ofrecimiento creado, 1 minuta generada"

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["oferta_borrador_creado"] is True
        assert entrada["minuta_ejecutada"] is True


class TestDemandantesValidos:
    def _evaluacion_valida(self, **overrides):
        base = {
            "demandantes": [{"apellido": "Pérez", "monto_recargo_30": 500000, "monto_afc": 200000}],
            "hay_discrepancia": False,
            "detalle_discrepancia": "",
        }
        base.update(overrides)
        return base

    def test_devuelve_la_lista_cuando_es_valida(self):
        evaluacion = self._evaluacion_valida()
        assert agenda._demandantes_validos(evaluacion) == evaluacion["demandantes"]

    def test_none_cuando_falta_la_clave_demandantes(self):
        evaluacion = {"hay_discrepancia": False, "detalle_discrepancia": ""}
        assert agenda._demandantes_validos(evaluacion) is None

    def test_none_cuando_demandantes_es_lista_vacia(self):
        evaluacion = self._evaluacion_valida(demandantes=[])
        assert agenda._demandantes_validos(evaluacion) is None

    def test_none_cuando_un_monto_es_string_en_vez_de_entero(self):
        evaluacion = self._evaluacion_valida(
            demandantes=[{"apellido": "Pérez", "monto_recargo_30": "500000", "monto_afc": 200000}]
        )
        assert agenda._demandantes_validos(evaluacion) is None

    def test_none_cuando_falta_apellido(self):
        evaluacion = self._evaluacion_valida(
            demandantes=[{"monto_recargo_30": 500000, "monto_afc": 200000}]
        )
        assert agenda._demandantes_validos(evaluacion) is None

    def test_none_cuando_la_respuesta_no_es_un_dict(self):
        assert agenda._demandantes_validos(["no", "es", "un", "dict"]) is None


class TestEvaluarMontosOfrecimiento:
    def test_pasa_ruta_archivo_y_texto_del_cuadro_a_reasoning(self, tmp_path, monkeypatch):
        ruta_demanda = tmp_path / "demanda.pdf"
        llamadas = []

        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None, **_kwargs):
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
        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None, **_kwargs):
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


class TestDestinatariosRespuesta:
    def test_incluye_participante_que_solo_aparece_en_to_o_cc(self, monkeypatch):
        monkeypatch.setattr(
            agenda.gmail_client, "leer_hilo",
            lambda thread_id, **k: [
                {
                    "sender": "Cristina Gil <cgil@gomezyriesco.cl>",
                    "to": "Román Gómez <rgomez@gomezyriesco.cl>, Cristina Gil <cgil@gomezyriesco.cl>",
                    "cc": "Otro Interno <ointerno@gomezyriesco.cl>",
                },
            ],
        )

        destinatarios = agenda._destinatarios_respuesta("thread-1")

        assert destinatarios == "cgil@gomezyriesco.cl, rgomez@gomezyriesco.cl, ointerno@gomezyriesco.cl"

    def test_excluye_cuenta_de_trabajo_y_externos_y_dedupe(self, monkeypatch):
        monkeypatch.setattr(
            agenda.gmail_client, "leer_hilo",
            lambda thread_id, **k: [
                {
                    "sender": "Nico Muñoz <nmunoz@gomezyriesco.cl>",
                    "to": "Román Gómez <rgomez@gomezyriesco.cl>, Cliente Externo <cliente@externo.cl>",
                    "cc": "",
                },
                {
                    "sender": "Román Gómez <rgomez@gomezyriesco.cl>",
                    "to": "Nico Muñoz <nmunoz@gomezyriesco.cl>",
                    "cc": "",
                },
            ],
        )

        destinatarios = agenda._destinatarios_respuesta("thread-1")

        assert destinatarios == "rgomez@gomezyriesco.cl"


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
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)

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
        # El asunto de la respuesta es el asunto REAL de la cadena encontrada
        # (del mock de leer_hilo), no el reconstruido por
        # _armar_asunto_ofrecimiento (que incluiría la palabra "Rit").
        assert asunto == 'Re: Demanda laboral "Perez con Alvi" M-1-2026'

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
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)

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
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)

        monkeypatch.setattr(agenda.gmail_client, "buscar_hilos", lambda query, **k: [{"id": "thread-interno"}])
        monkeypatch.setattr(
            agenda.gmail_client, "leer_hilo",
            lambda thread_id, **k: [{"sender": "cgil@gomezyriesco.cl", "cuerpo_texto": "x", "subject": "x"}],
        )
        borrador_propio = {
            "id": "draft-existente",
            "message": {"payload": {"headers": [
                {"name": "Subject", "value": 'Demanda laboral "Perez con Alvi" Rit M-1-2026'},
            ]}},
        }
        monkeypatch.setattr(agenda.gmail_client, "listar_borradores_de_hilo", lambda thread_id, **k: [borrador_propio])

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
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)

        monkeypatch.setattr(agenda.gmail_client, "buscar_hilos", lambda query, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "buscar_borrador_por_asunto", lambda fragmento, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "leer_hilo", lambda thread_id, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-3"})

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        accion_discrepancia = next(a for a in resumen["acciones"] if "Discrepancia" in a["que"])
        assert accion_discrepancia["urgencia"] == "alta"
        assert "500.000" in accion_discrepancia["que"]

    def test_anota_accion_si_claude_no_devuelve_demandantes(self, tmp_path, monkeypatch):
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        monkeypatch.setattr(
            agenda.reasoning, "preguntar",
            lambda *a, **k: {"hay_discrepancia": False, "detalle_discrepancia": ""},
        )
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)
        monkeypatch.setattr(agenda.gmail_client, "leer_hilo", lambda thread_id, **k: [])

        llamadas_crear = []
        monkeypatch.setattr(agenda.gmail_client, "crear_borrador", lambda *a, **k: llamadas_crear.append(1))

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert llamadas_crear == []
        assert len(resumen["acciones"]) == 1
        assert "formato esperado" in resumen["acciones"][0]["que"]
        assert resumen["acciones"][0]["urgencia"] == "media"
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada.get("oferta_borrador_creado") is not True

    def test_anota_accion_si_claude_devuelve_lista_de_demandantes_vacia(self, tmp_path, monkeypatch):
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch, demandantes=[])
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)
        monkeypatch.setattr(agenda.gmail_client, "leer_hilo", lambda thread_id, **k: [])

        llamadas_crear = []
        monkeypatch.setattr(agenda.gmail_client, "crear_borrador", lambda *a, **k: llamadas_crear.append(1))

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert llamadas_crear == []
        assert len(resumen["acciones"]) == 1
        assert "formato esperado" in resumen["acciones"][0]["que"]

    def test_no_genera_ofrecimiento_si_causa_ya_tiene_estado_acuerdo(self, tmp_path, monkeypatch):
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path, estado_acuerdo="pendiente_pago")
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch)
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)

        llamadas_crear = []
        monkeypatch.setattr(agenda.gmail_client, "crear_borrador", lambda *a, **k: llamadas_crear.append(1))

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert llamadas_crear == []
        assert resumen["items"] == []
        assert resumen["metricas"][1] == {"etiqueta": "Borradores de ofrecimiento creados", "valor": 0}

    def test_borrador_ajeno_en_la_cadena_no_se_confunde_con_el_de_ofrecimiento(self, tmp_path, monkeypatch):
        """Si la cadena interna ya tiene un borrador cuyo asunto no menciona
        el RIT (una respuesta ajena a medio escribir), no se lo debe tratar
        como si fuera el de ofrecimiento: hay que crear uno nuevo y avisar
        con una acción."""
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch)
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)

        monkeypatch.setattr(agenda.gmail_client, "buscar_hilos", lambda query, **k: [{"id": "thread-interno"}])
        monkeypatch.setattr(
            agenda.gmail_client, "leer_hilo",
            lambda thread_id, **k: [{
                "sender": "cgil@gomezyriesco.cl", "cuerpo_texto": "x",
                "subject": 'Demanda laboral "Perez con Alvi" M-1-2026',
            }],
        )
        borrador_ajeno = {
            "id": "draft-ajeno",
            "message": {"payload": {"headers": [
                {"name": "Subject", "value": "Re: otra consulta sin relación"},
            ]}},
        }
        monkeypatch.setattr(agenda.gmail_client, "listar_borradores_de_hilo", lambda thread_id, **k: [borrador_ajeno])

        llamadas_crear = []
        monkeypatch.setattr(
            agenda.gmail_client, "crear_borrador",
            lambda destinatario, asunto, cuerpo, **k: llamadas_crear.append((destinatario, asunto, cuerpo, k)) or {"id": "draft-nuevo"},
        )

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert len(llamadas_crear) == 1
        _destinatario, asunto, _cuerpo, kwargs = llamadas_crear[0]
        assert kwargs["thread_id"] == "thread-interno"
        assert asunto == 'Re: Demanda laboral "Perez con Alvi" M-1-2026'

        accion = next(a for a in resumen["acciones"] if "no menciona el RIT" in a["que"])
        assert accion["urgencia"] == "media"
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["oferta_borrador_creado"] is True

    def test_no_recrea_si_hay_un_borrador_ajeno_y_tambien_uno_propio_en_la_cadena(self, tmp_path, monkeypatch):
        """Si la cadena tiene varios borradores y AL MENOS UNO sí menciona
        el RIT, ese es el nuestro — se reusa sin crear uno nuevo, aunque
        también haya un borrador ajeno sin relación en la misma cadena."""
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(monkeypatch)
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)

        monkeypatch.setattr(agenda.gmail_client, "buscar_hilos", lambda query, **k: [{"id": "thread-interno"}])
        monkeypatch.setattr(
            agenda.gmail_client, "leer_hilo",
            lambda thread_id, **k: [{"sender": "cgil@gomezyriesco.cl", "cuerpo_texto": "x", "subject": "x"}],
        )
        borrador_ajeno = {
            "id": "draft-ajeno",
            "message": {"payload": {"headers": [{"name": "Subject", "value": "Re: otra consulta sin relación"}]}},
        }
        borrador_propio = {
            "id": "draft-propio",
            "message": {"payload": {"headers": [
                {"name": "Subject", "value": 'Demanda laboral "Perez con Alvi" Rit M-1-2026'},
            ]}},
        }
        monkeypatch.setattr(
            agenda.gmail_client, "listar_borradores_de_hilo",
            lambda thread_id, **k: [borrador_ajeno, borrador_propio],
        )

        llamadas_crear = []
        monkeypatch.setattr(agenda.gmail_client, "crear_borrador", lambda *a, **k: llamadas_crear.append(1))

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert llamadas_crear == []
        assert not any("no menciona el RIT" in a["que"] for a in resumen["acciones"])
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["oferta_borrador_creado"] is True

    def test_escapa_html_en_el_apellido_del_demandante(self, tmp_path, monkeypatch):
        """El apellido es texto libre extraído por Claude de un PDF; si
        contiene caracteres especiales de HTML (&, <, >), no debe romper el
        cuerpo HTML del borrador ni renderizar mal."""
        ruta_registro = self._causa_lista_para_ofrecimiento(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"},
        })
        self._mock_evaluacion(
            monkeypatch,
            demandantes=[{"apellido": "O'Brien & <Hijos>", "monto_recargo_30": 500000, "monto_afc": 200000}],
        )
        monkeypatch.setattr(agenda.bitacora_mod, "registrar", lambda *a, **k: None)

        monkeypatch.setattr(agenda.gmail_client, "buscar_hilos", lambda query, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "buscar_borrador_por_asunto", lambda fragmento, **k: [])
        monkeypatch.setattr(agenda.gmail_client, "leer_hilo", lambda thread_id, **k: [])

        llamadas_crear = []
        monkeypatch.setattr(
            agenda.gmail_client, "crear_borrador",
            lambda destinatario, asunto, cuerpo, **k: llamadas_crear.append((destinatario, asunto, cuerpo, k)) or {"id": "draft-4"},
        )

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        _correr_agenda(contexto, tmp_path, ruta_registro_causas=ruta_registro)

        assert len(llamadas_crear) == 1
        _destinatario, _asunto, cuerpo, _kwargs = llamadas_crear[0]
        assert "&amp;" in cuerpo
        assert "&lt;Hijos&gt;" in cuerpo
        assert "<Hijos>" not in cuerpo
        # Los <br> propios (agregados después de escapar) no deben quedar
        # doblemente escapados.
        assert "<br>" in cuerpo
        assert "&lt;br&gt;" not in cuerpo
