import json

from gestion_causas import registro as registro_mod
from gestion_causas.fases import smu


class TestRutaActualizadorInformes:
    def test_usa_el_valor_por_defecto_si_no_hay_variable_de_entorno(self, monkeypatch):
        monkeypatch.delenv("RUTA_ACTUALIZADOR_INFORMES", raising=False)
        assert smu._ruta_actualizador_informes() == smu._RUTA_ACTUALIZADOR_INFORMES_DEFAULT

    def test_usa_la_variable_de_entorno_si_esta_definida(self, monkeypatch):
        monkeypatch.setenv("RUTA_ACTUALIZADOR_INFORMES", "D:\\otra\\ruta")
        assert smu._ruta_actualizador_informes() == "D:\\otra\\ruta"


class TestCorrerSinHilosNuevos:
    def test_devuelve_resumen_sin_novedades(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        contexto = {"fecha_hoy": "2026-09-16"}

        resumen = smu.correr(contexto, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert resumen["fase"] == "smu"
        assert resumen["titular"] == "Sin correos nuevos"
        assert resumen["items"] == []


def _hilo_falso(mensajes):
    """Arma el dict que devuelve gmail_client.leer_hilo (ya aplanado)."""
    return mensajes


class TestOrigenDeLaCadena:
    def test_dominio_smu_cl_es_valido_sin_llamar_a_claude(self, tmp_path, monkeypatch):
        llamadas_reasoning = []
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda *a, **k: llamadas_reasoning.append(1))
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: _hilo_falso([
            {"id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
             "cuerpo_texto": "cuadro incompleto a proposito", "adjuntos": []},
        ]))

        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert llamadas_reasoning == []

    def test_dominio_gomezyriesco_sin_cita_no_llama_a_claude_y_es_invalida(self, tmp_path, monkeypatch):
        llamadas_reasoning = []
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda *a, **k: llamadas_reasoning.append(1))
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: _hilo_falso([
            {"id": "msg-1", "thread_id": "thread-1", "sender": "nmunoz@gomezyriesco.cl", "subject": "Re: causa",
             "cuerpo_texto": "Román, ¿cómo contestamos esta?", "adjuntos": []},
        ]))

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert llamadas_reasoning == []
        assert resumen["items"] == []

    def test_otro_dominio_no_llama_a_claude_ni_se_procesa(self, tmp_path, monkeypatch):
        llamadas = []
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda *a, **k: llamadas.append(1))
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: _hilo_falso([
            {"id": "msg-1", "thread_id": "thread-1", "sender": "alguien@gmail.com", "subject": "DEMANDA",
             "cuerpo_texto": "no es de las empresas", "adjuntos": []},
        ]))

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert llamadas == []
        assert resumen["items"] == []


CUERPO_CUADRO_ALVI = """\
Rit: M-1-2026
Tribunal: Juzgado de Letras del Trabajo de Temuco
Demandante: JUAN PEREZ
Demandada: Alvi
Cuantía: $500.000
Materia: Despido injustificado
"""


class TestEsReenvioDeCuadroConfiable:
    def test_sin_texto_citado_no_es_reenvio(self):
        mensaje = {"cuerpo_texto": "Román, ¿cómo contestamos esta?"}
        assert smu._es_reenvio_de_cuadro_confiable(mensaje) is False

    def test_cita_cuadro_completo_de_smu_cl_es_reenvio(self):
        mensaje = {"cuerpo_texto": (
            "Román, te reenvío esto.\n\n"
            "---------- Mensaje original ----------\n"
            "De: Persona SMU <persona@smu.cl>\n"
            + CUERPO_CUADRO_ALVI
        )}
        assert smu._es_reenvio_de_cuadro_confiable(mensaje) is True

    def test_cita_cuadro_completo_de_sb_cl_es_reenvio(self):
        mensaje = {"cuerpo_texto": (
            "> De: Persona <persona@sb.cl>\n> " + CUERPO_CUADRO_ALVI.replace("\n", "\n> ")
        )}
        assert smu._es_reenvio_de_cuadro_confiable(mensaje) is True

    def test_cita_cuadro_completo_pero_de_dominio_no_confiable_no_es_reenvio(self):
        mensaje = {"cuerpo_texto": (
            "---------- Mensaje original ----------\n"
            "De: Alguien <alguien@gmail.com>\n"
            + CUERPO_CUADRO_ALVI
        )}
        assert smu._es_reenvio_de_cuadro_confiable(mensaje) is False

    def test_cita_de_smu_cl_pero_cuadro_incompleto_no_es_reenvio(self):
        mensaje = {"cuerpo_texto": (
            "---------- Mensaje original ----------\n"
            "De: Persona SMU <persona@smu.cl>\n"
            "Demandada: Alvi\n"
        )}
        assert smu._es_reenvio_de_cuadro_confiable(mensaje) is False

    def test_origen_cadena_dominio_smu_cl_directo_no_necesita_evaluar_cita(self):
        assert smu._origen_cadena({"sender": "persona@smu.cl", "cuerpo_texto": ""}) == {"valida": True}

    def test_origen_cadena_gomezyriesco_delega_en_es_reenvio_de_cuadro_confiable(self):
        mensaje = {"sender": "nmunoz@gomezyriesco.cl", "cuerpo_texto": "sin citas"}
        assert smu._origen_cadena(mensaje) == {"valida": False}


class TestFiltroDeEmpresaYDuplicados:
    def test_empresa_no_valida_no_genera_item(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI.replace("Alvi", "Falabella"), "adjuntos": [],
        }])

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert resumen["items"] == []

    def test_cuadro_incompleto_no_genera_item_y_lo_anota(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": "Demandada: Alvi\n", "adjuntos": [],
        }])

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert resumen["items"] == []
        assert any("cuadro" in n["detalle"].lower() for n in resumen["notas"])

    def test_cuadro_incompleto_de_salcobrand_se_anota_distinto_y_marca_procesado(self, tmp_path, monkeypatch):
        etiquetas_aplicadas = []
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA Salcobrand",
            "cuerpo_texto": "Les enviamos la demanda de Salcobrand, sin cuadro-resumen.", "adjuntos": [],
        }])
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda *a, **k: "label-procesado")
        monkeypatch.setattr(
            smu.gmail_client, "aplicar_etiqueta_a_hilo",
            lambda thread_id, label_id, servicio=None: etiquetas_aplicadas.append((thread_id, label_id)),
        )

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert resumen["items"] == []
        assert not any("mal formado" in n["detalle"].lower() for n in resumen["notas"])
        assert any(
            n["tipo"] == "empresa_sin_cuadro_automatico" and "Salcobrand" in n["detalle"]
            for n in resumen["notas"]
        )
        assert etiquetas_aplicadas == [("thread-1", "label-procesado")]

    def test_salcobrand_sin_cuadro_saca_los_datos_de_la_demanda_y_sigue_el_flujo(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Minutas" / "Dinares con Salcobrand O-396-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        llamadas_agregar_causa = []
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: llamadas_agregar_causa.append(datos))
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None, **_kwargs: (
            {"rit": "O-396-2026", "tribunal": "Juzgado de Letras del Trabajo de Temuco",
             "demandante": "Marianela Viviana Dinares Yañez", "materia": None}
            if schema is smu.SCHEMA_CAMPOS_DEMANDA
            else {"fecha_despido": "2026-08-01", "ajuste_base_calculo": False, "otros_ajustes": []}
        ))
        etiquetas_aplicadas = []
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: f"label-{nombre}")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: etiquetas_aplicadas.append(label_id))
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "Camila <cqueralto@sb.cl>",
            "subject": "Notificacion demanda laboral Dinares con Salcobrand",
            "date": "Fri, 25 Sep 2026 08:00:00 -0300",
            "cuerpo_texto": "Hola Roman,\n\nAdjunto demanda laboral de Marianela Viviana Dinares Yañez.",
            "adjuntos": [{"filename": "Epson_20260924.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 8300391}],
        }])

        ruta_registro = tmp_path / "registro_causas.json"
        resumen = smu.correr({"fecha_hoy": "2026-09-25"}, ruta_registro_causas=ruta_registro)

        entrada = registro_mod.obtener_causa("O-396-2026", ruta=ruta_registro)
        assert entrada["empresa"] == "Salcobrand"
        assert entrada["borrador_documentos_draft_id"] == "draft-1"
        assert entrada["aplica_excel"] is False
        assert llamadas_agregar_causa == []
        assert "label-Salcobrand" in etiquetas_aplicadas
        assert f"label-{smu.ETIQUETA_PROCESADO}" in etiquetas_aplicadas
        assert resumen["items"] == [{"rit": "O-396-2026", "titulo": "Salcobrand - Marianela Viviana Dinares Yañez"}]
        assert not any(n["tipo"] == "empresa_sin_cuadro_automatico" for n in resumen["notas"])

    def test_salcobrand_sin_cuadro_si_falla_la_lectura_no_marca_procesado(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda *a, **k: {"error": "timeout"})
        etiquetas_aplicadas = []
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: f"label-{nombre}")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: etiquetas_aplicadas.append(label_id))
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "cqueralto@sb.cl",
            "subject": "Notificacion demanda laboral Dinares con Salcobrand", "cuerpo_texto": "Adjunto demanda.",
            "adjuntos": [{"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 8300391}],
        }])

        resumen = smu.correr({"fecha_hoy": "2026-09-25"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert resumen["items"] == []
        assert etiquetas_aplicadas == []
        assert any("timeout" in a["que"] for a in resumen["acciones"])

    def test_hilo_iniciado_antes_del_corte_se_ignora_aunque_tenga_cuadro(self, tmp_path, monkeypatch):
        llamadas = []
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda *a, **k: llamadas.append(1))
        etiquetas_aplicadas = []
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: f"label-{nombre}")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: etiquetas_aplicadas.append(label_id))
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [
            {"id": "msg-1", "thread_id": "thread-1", "sender": "nalquinta@smu.cl", "subject": "DEMANDA RIT M-21-2025",
             "date": "Fri, 6 Jun 2025 19:51:39 +0000", "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": []},
            {"id": "msg-2", "thread_id": "thread-1", "sender": "nmunoz@gomezyriesco.cl", "subject": "Re: DEMANDA",
             "date": "Fri, 25 Sep 2026 05:10:28 -0700", "cuerpo_texto": "Etapa de pago.", "adjuntos": []},
        ])

        ruta_registro = tmp_path / "registro_causas.json"
        resumen = smu.correr({"fecha_hoy": "2026-09-25"}, ruta_registro_causas=ruta_registro)

        assert resumen["items"] == []
        assert llamadas == []
        assert registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro) is None
        assert etiquetas_aplicadas == [f"label-{smu.ETIQUETA_PROCESADO}"]

    def test_rit_ya_registrado_no_genera_item_nuevo(self, tmp_path, monkeypatch):
        ruta_registro = tmp_path / "registro_causas.json"
        registro_mod.registrar_causa("M-1-2026", {"empresa": "Alvi"}, ruta=ruta_registro)

        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [],
        }])

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        assert resumen["items"] == []


class TestCrearCarpetaYGuardarDemanda:
    def test_crea_carpeta_y_guarda_el_pdf_de_la_demanda(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: f"label-{nombre}")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None, **_kwargs: (
            {"fecha_despido": "2026-01-08", "ajuste_base_calculo": False, "otros_ajustes": []}
            if schema is smu.SCHEMA_AJUSTES_DEMANDA else {"resumen": "Texto de prueba."}
        ))

        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [
                {"filename": "demanda_original.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert (carpeta_causa / "demanda.pdf").exists()
        assert resumen["metricas"] == [
            {"etiqueta": "Causas nuevas", "valor": 1},
            {"etiqueta": "Borradores de documentos creados", "valor": 1},
            {"etiqueta": "EERR reusado", "valor": 0},
        ]


class TestDemandaYaEnCarpeta:
    def test_demanda_no_guardada_esta_corrida_pero_ya_existe_en_disco_sigue_el_flujo(self, tmp_path, monkeypatch):
        """Simula una carpeta que Nico armó a mano antes de esta automatización,
        con la demanda ya adentro, para un RIT que aún no estaba en el registro
        JSON. guardar_adjunto devuelve guardado=False (el archivo "ya existía"),
        pero el archivo demanda.pdf sigue estando ahí en disco — el flujo
        completo (ajustes, EERR, lista, borrador) debe seguir corriendo."""
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        carpeta_causa.mkdir(parents=True)
        (carpeta_causa / "demanda.pdf").write_bytes(b"demanda ya existente en disco")

        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: carpeta_causa)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(
            smu.carpetas_mod, "guardar_adjunto",
            lambda carpeta, nombre, contenido: {"ruta": carpeta / nombre, "guardado": False},
        )
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})

        llamadas_ajustes = []

        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None, **_kwargs):
            if schema is smu.SCHEMA_AJUSTES_DEMANDA:
                llamadas_ajustes.append(1)
                return {"fecha_despido": "2026-01-08", "ajuste_base_calculo": False, "otros_ajustes": []}
            return {"resumen": "Texto de prueba."}

        monkeypatch.setattr(smu.reasoning, "preguntar", preguntar_falso)

        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])

        ruta_registro = tmp_path / "registro_causas.json"
        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        assert llamadas_ajustes == [1]
        assert not any(n["tipo"] == "sin_demanda" for n in resumen["notas"])

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["borrador_documentos_draft_id"] == "draft-1"
        assert entrada["documentos_solicitados"]


class TestResumenYExcel:
    def _monkeypatch_comunes(self, monkeypatch, tmp_path, empresa="Alvi"):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None, **_kwargs: (
            {"fecha_despido": "2026-01-08", "ajuste_base_calculo": False, "otros_ajustes": []}
            if schema is smu.SCHEMA_AJUSTES_DEMANDA else {"resumen": "Texto de prueba."}
        ))
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        cuerpo = CUERPO_CUADRO_ALVI.replace("Alvi", empresa) if empresa != "Alvi" else CUERPO_CUADRO_ALVI
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": cuerpo, "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])
        return carpeta_causa

    def test_llama_a_reasoning_para_el_resumen_y_escribe_la_fila_del_excel(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)

        llamadas_agregar_causa = []

        def agregar_causa_falso(ruta_excel, datos):
            llamadas_agregar_causa.append(datos)
            return {"agregada": True, "fila": 10}

        monkeypatch.setattr(smu, "agregar_causa", agregar_causa_falso)
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None, **_kwargs: {"resumen": "Texto de prueba del resumen."})

        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert len(llamadas_agregar_causa) == 1
        datos = llamadas_agregar_causa[0]
        assert datos["causa"] == "M-1-2026"
        assert datos["resumen"] == "Texto de prueba del resumen."
        assert datos["juzgado"] == "Juzgado de Letras del Trabajo de Temuco"

    def test_preunic_y_salcobrand_no_escriben_fila_de_excel(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path, empresa="Preunic")

        llamadas_agregar_causa = []
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: llamadas_agregar_causa.append(datos))
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None, **_kwargs: {"resumen": "Texto de prueba."})

        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert llamadas_agregar_causa == []


class TestRegistrarEtiquetarYMarcarProcesado:
    def test_registra_la_causa_etiqueta_y_marca_procesado(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None, **_kwargs: {"resumen": "Texto de prueba."})

        etiquetas_aplicadas = []
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: f"label-{nombre}")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: etiquetas_aplicadas.append((thread_id, label_id)))
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})

        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])

        ruta_registro = tmp_path / "registro_causas.json"
        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["empresa"] == "Alvi"
        assert entrada["carpeta"] == str(carpeta_causa)
        assert entrada["thread_id"] == "thread-1"
        assert entrada["tiene_demanda"] is True
        assert entrada["aplica_excel"] is True

        assert ("thread-1", "label-Alvi") in etiquetas_aplicadas
        assert ("thread-1", f"label-{smu.ETIQUETA_PROCESADO}") in etiquetas_aplicadas

        assert resumen["items"] == [{"rit": "M-1-2026", "titulo": "Alvi - Juan Perez"}]


class TestBuscarCecoEnMensajes:
    def test_encuentra_ceco_en_el_primer_mensaje(self):
        mensajes = [{"cuerpo_texto": "Les confirmamos el CECO: T-4521 para esta causa."}]
        assert smu._buscar_ceco_en_mensajes(mensajes) == "T-4521"

    def test_encuentra_ceco_en_un_mensaje_posterior(self):
        mensajes = [
            {"cuerpo_texto": "Estimados, queda pendiente el CECO."},
            {"cuerpo_texto": "El CECO es 8890."},
        ]
        assert smu._buscar_ceco_en_mensajes(mensajes) == "8890"

    def test_sin_ceco_en_ningun_mensaje_devuelve_none(self):
        mensajes = [{"cuerpo_texto": "No hay CECO mencionado acá."}]
        assert smu._buscar_ceco_en_mensajes(mensajes) is None


class TestAjustesDeLaDemanda:
    def _monkeypatch_comunes(self, monkeypatch, tmp_path):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])
        return carpeta_causa

    def test_llama_a_reasoning_con_ruta_archivo_y_guarda_fecha_despido_y_ceco(self, tmp_path, monkeypatch):
        carpeta_causa = self._monkeypatch_comunes(monkeypatch, tmp_path)
        llamadas = []

        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None, **_kwargs):
            if schema is smu.SCHEMA_AJUSTES_DEMANDA:
                llamadas.append(ruta_archivo)
                return {"fecha_despido": "2026-01-08", "ajuste_base_calculo": False, "otros_ajustes": []}
            return {"resumen": "Texto de prueba."}

        monkeypatch.setattr(smu.reasoning, "preguntar", preguntar_falso)

        ruta_registro = tmp_path / "registro_causas.json"
        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        assert llamadas == [carpeta_causa / "demanda.pdf"]
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["fecha_despido"] == "2026-01-08"

    def test_guarda_el_ceco_encontrado_en_los_mensajes(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI + "\nCECO: T-900\n", "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None, **_kwargs: (
            {"fecha_despido": "2026-01-08", "ajuste_base_calculo": False, "otros_ajustes": []}
            if schema is smu.SCHEMA_AJUSTES_DEMANDA else {"resumen": "Texto de prueba."}
        ))

        ruta_registro = tmp_path / "registro_causas.json"
        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["ceco"] == "T-900"

    def test_sin_demanda_guardada_no_llama_a_reasoning_de_ajustes(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [],
        }])

        llamadas_ajustes = []

        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None, **_kwargs):
            if schema is smu.SCHEMA_AJUSTES_DEMANDA:
                llamadas_ajustes.append(1)
                return {"fecha_despido": None, "ajuste_base_calculo": False, "otros_ajustes": []}
            return {"resumen": "Texto de prueba."}

        monkeypatch.setattr(smu.reasoning, "preguntar", preguntar_falso)

        ruta_registro = tmp_path / "registro_causas.json"
        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        assert llamadas_ajustes == []
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["fecha_despido"] is None

    def test_error_al_evaluar_ajustes_sube_la_urgencia_a_alta_y_advierte_en_bitacora(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)

        def preguntar_falso(tarea, contexto, schema, ruta_archivo=None, **_kwargs):
            if schema is smu.SCHEMA_AJUSTES_DEMANDA:
                return {"error": "Claude no devolvió JSON válido tras 2 intentos."}
            return {"resumen": "Texto de prueba."}

        monkeypatch.setattr(smu.reasoning, "preguntar", preguntar_falso)

        mensajes_bitacora = []
        monkeypatch.setattr(smu.bitacora_mod, "registrar", lambda mensaje, rit=None: mensajes_bitacora.append(mensaje))

        ruta_registro = tmp_path / "registro_causas.json"
        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        acciones_ajustes = [a for a in resumen["acciones"] if "ajustes de la demanda" in a["que"]]
        assert len(acciones_ajustes) == 1
        assert acciones_ajustes[0]["urgencia"] == "alta"
        assert any("ADVERTENCIA" in mensaje for mensaje in mensajes_bitacora)

        # A pesar del error, el borrador se crea igual con la lista base (mejor
        # un borrador incompleto que ninguno) y la causa queda registrada.
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["borrador_documentos_draft_id"] == "draft-1"


class TestReusoDeEerr:
    def _monkeypatch_comunes(self, monkeypatch, tmp_path, cuerpo_extra=""):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI + cuerpo_extra, "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None, **_kwargs: (
            {"fecha_despido": "2026-01-08", "ajuste_base_calculo": False, "otros_ajustes": []}
            if schema is smu.SCHEMA_AJUSTES_DEMANDA else {"resumen": "Texto de prueba."}
        ))
        return carpeta_causa

    def test_copia_el_eerr_de_la_causa_anterior_cuando_hay_uno_reusable(self, tmp_path, monkeypatch):
        carpeta_causa = self._monkeypatch_comunes(monkeypatch, tmp_path, cuerpo_extra="\nCECO: T-900\n")

        carpeta_causa_anterior = tmp_path / "Minutas" / "Soto con Alvi M-9-2025"
        carpeta_causa_anterior.mkdir(parents=True)
        (carpeta_causa_anterior / "EERR 2025.pdf").write_bytes(b"eerr viejo")

        ruta_registro = tmp_path / "registro_causas.json"
        registro_mod.registrar_causa("M-9-2025", {"carpeta": str(carpeta_causa_anterior)}, ruta=ruta_registro)

        ruta_ceco = tmp_path / "registro_ceco.json"
        registro_mod.registrar_eerr_recibido("T-900", "2025-11-01", "M-9-2025", ruta=ruta_ceco)

        smu.correr(
            {"fecha_hoy": "2026-09-16"},
            ruta_registro_causas=ruta_registro,
            ruta_registro_ceco=ruta_ceco,
        )

        assert (carpeta_causa / "EERR 2025.pdf").exists()

    def test_sin_eerr_reusable_no_copia_nada(self, tmp_path, monkeypatch):
        carpeta_causa = self._monkeypatch_comunes(monkeypatch, tmp_path, cuerpo_extra="\nCECO: T-901\n")

        ruta_registro = tmp_path / "registro_causas.json"
        ruta_ceco = tmp_path / "registro_ceco.json"

        smu.correr(
            {"fecha_hoy": "2026-09-16"},
            ruta_registro_causas=ruta_registro,
            ruta_registro_ceco=ruta_ceco,
        )

        assert list(carpeta_causa.iterdir()) == [carpeta_causa / "demanda.pdf"]

    def test_causa_anterior_sin_archivo_eerr_no_quita_el_item_de_la_lista(self, tmp_path, monkeypatch):
        """Aunque buscar_eerr_reusable encuentre una entrada de CECO, si la
        causa anterior no tiene ningún archivo que parece_eerr en su carpeta
        (o no tiene carpeta), no se copia nada — y por lo tanto el item del
        EERR no debe quitarse de la lista de documentos a solicitar."""
        self._monkeypatch_comunes(monkeypatch, tmp_path, cuerpo_extra="\nCECO: T-900\n")

        carpeta_causa_anterior = tmp_path / "Minutas" / "Soto con Alvi M-9-2025"
        carpeta_causa_anterior.mkdir(parents=True)
        (carpeta_causa_anterior / "Otro documento.pdf").write_bytes(b"no es un eerr")

        ruta_registro = tmp_path / "registro_causas.json"
        registro_mod.registrar_causa("M-9-2025", {"carpeta": str(carpeta_causa_anterior)}, ruta=ruta_registro)

        ruta_ceco = tmp_path / "registro_ceco.json"
        registro_mod.registrar_eerr_recibido("T-900", "2025-11-01", "M-9-2025", ruta=ruta_ceco)

        smu.correr(
            {"fecha_hoy": "2026-09-16"},
            ruta_registro_causas=ruta_registro,
            ruta_registro_ceco=ruta_ceco,
        )

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert "EERR del local de los años 2024, 2025 y 2026" in entrada["documentos_solicitados"]


class TestArmarListaDocumentos:
    def test_lista_base_sin_ajustes_ni_reuso(self):
        lista = smu._armar_lista_documentos({"ajuste_base_calculo": False, "otros_ajustes": []}, eerr_reusado=False)
        assert lista == [
            "Contrato de trabajo y anexos",
            "Carta de despido",
            "Finiquito",
            "EERR del local de los años 2024, 2025 y 2026",
            "Comparativa de dotación del local antes y después del despido",
            "Testigos",
            "Absolvente",
        ]

    def test_con_reuso_de_eerr_quita_el_punto_del_eerr(self):
        lista = smu._armar_lista_documentos({"ajuste_base_calculo": False, "otros_ajustes": []}, eerr_reusado=True)
        assert not any("EERR" in d for d in lista)
        assert len(lista) == 6

    def test_ajuste_base_calculo_agrega_liquidaciones_antes_de_testigos(self):
        lista = smu._armar_lista_documentos({"ajuste_base_calculo": True, "otros_ajustes": []}, eerr_reusado=False)
        indice = lista.index("Últimas 6 liquidaciones de remuneraciones")
        assert indice == lista.index("Testigos") - 1

    def test_otros_ajustes_se_agregan_antes_de_testigos_en_orden(self):
        lista = smu._armar_lista_documentos(
            {"ajuste_base_calculo": False, "otros_ajustes": ["Antecedentes del préstamo", "Registro de horas extra"]},
            eerr_reusado=False,
        )
        indice_testigos = lista.index("Testigos")
        assert lista[indice_testigos - 2] == "Antecedentes del préstamo"
        assert lista[indice_testigos - 1] == "Registro de horas extra"

    def test_ajuste_base_calculo_y_otros_ajustes_combinados(self):
        lista = smu._armar_lista_documentos(
            {"ajuste_base_calculo": True, "otros_ajustes": ["Antecedentes del préstamo"]},
            eerr_reusado=True,
        )
        assert not any("EERR" in d for d in lista)
        indice_testigos = lista.index("Testigos")
        assert lista[indice_testigos - 2] == "Últimas 6 liquidaciones de remuneraciones"
        assert lista[indice_testigos - 1] == "Antecedentes del préstamo"


class TestCrearBorradorDeDocumentos:
    def _monkeypatch_comunes(self, monkeypatch, tmp_path):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA Rit M-1-2026",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [
                {"filename": "demanda.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema, ruta_archivo=None, **_kwargs: (
            {"fecha_despido": "2026-01-08", "ajuste_base_calculo": False, "otros_ajustes": []}
            if schema is smu.SCHEMA_AJUSTES_DEMANDA else {"resumen": "Texto de prueba."}
        ))
        return carpeta_causa

    def test_crea_el_borrador_como_respuesta_del_hilo_con_lista_html(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])

        llamadas = []
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: llamadas.append((a, k)) or {"id": "draft-1"})

        ruta_registro = tmp_path / "registro_causas.json"
        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        assert len(llamadas) == 1
        args, kwargs = llamadas[0]
        assert args[0] == "persona@smu.cl"
        assert "M-1-2026" in args[1] or "DEMANDA" in args[1]
        assert "<ol>" in args[2] and "<li>Contrato de trabajo y anexos</li>" in args[2]
        assert kwargs["thread_id"] == "thread-1"
        assert kwargs["html"] is True

        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["borrador_documentos_draft_id"] == "draft-1"
        assert entrada["documentos_solicitados"][0] == "Contrato de trabajo y anexos"

    def test_no_duplica_borrador_si_la_cadena_ya_tiene_uno(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [{"id": "draft-viejo"}])

        llamadas = []
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: llamadas.append(1) or {"id": "draft-nuevo"})

        ruta_registro = tmp_path / "registro_causas.json"
        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=ruta_registro)

        assert llamadas == []
        entrada = registro_mod.obtener_causa("M-1-2026", ruta=ruta_registro)
        assert entrada["borrador_documentos_draft_id"] == "draft-viejo"

    def test_metricas_incluyen_borradores_creados_y_eerr_reusado(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        etiquetas = {m["etiqueta"] for m in resumen["metricas"]}
        assert "Borradores de documentos creados" in etiquetas
        assert "EERR reusado" in etiquetas

    def test_bitacora_menciona_el_borrador_creado(self, tmp_path, monkeypatch):
        self._monkeypatch_comunes(monkeypatch, tmp_path)
        monkeypatch.setattr(smu.gmail_client, "listar_borradores_de_hilo", lambda thread_id: [])
        monkeypatch.setattr(smu.gmail_client, "crear_borrador", lambda *a, **k: {"id": "draft-1"})

        mensajes_bitacora = []
        monkeypatch.setattr(smu.bitacora_mod, "registrar", lambda mensaje, rit=None: mensajes_bitacora.append(mensaje))

        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert any("borrador" in m.lower() for m in mensajes_bitacora)
