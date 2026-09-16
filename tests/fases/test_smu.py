import json

from gestion_causas import registro as registro_mod
from gestion_causas.fases import smu


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

    def test_dominio_gomezyriesco_ambiguo_llama_a_claude(self, tmp_path, monkeypatch):
        llamadas = []

        def preguntar_falso(tarea, contexto, schema):
            llamadas.append(contexto)
            return {"es_reenvio_de_cuadro": False, "justificacion": "Nico iniciando una conversación"}

        monkeypatch.setattr(smu.reasoning, "preguntar", preguntar_falso)
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: _hilo_falso([
            {"id": "msg-1", "thread_id": "thread-1", "sender": "nmunoz@gomezyriesco.cl", "subject": "Re: causa",
             "cuerpo_texto": "Román, ¿cómo contestamos esta?", "adjuntos": []},
        ]))

        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert len(llamadas) == 1
        assert llamadas[0]["remitente"] == "nmunoz@gomezyriesco.cl"

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

        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [{"id": "thread-1"}])
        monkeypatch.setattr(smu.gmail_client, "leer_hilo", lambda thread_id: [{
            "id": "msg-1", "thread_id": "thread-1", "sender": "persona@smu.cl", "subject": "DEMANDA",
            "cuerpo_texto": CUERPO_CUADRO_ALVI, "adjuntos": [
                {"filename": "demanda_original.pdf", "attachment_id": "att-1", "mime_type": "application/pdf", "size": 50000},
            ],
        }])

        resumen = smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert (carpeta_causa / "demanda.pdf").exists()
        assert resumen["metricas"] == [{"etiqueta": "Causas nuevas", "valor": 1}]


class TestResumenYExcel:
    def _monkeypatch_comunes(self, monkeypatch, tmp_path, empresa="Alvi"):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: "label-id-1")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: None)
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
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema: {"resumen": "Texto de prueba del resumen."})

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
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema: {"resumen": "Texto de prueba."})

        smu.correr({"fecha_hoy": "2026-09-16"}, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert llamadas_agregar_causa == []


class TestRegistrarEtiquetarYMarcarProcesado:
    def test_registra_la_causa_etiqueta_y_marca_procesado(self, tmp_path, monkeypatch):
        carpeta_causa = tmp_path / "Minutas" / "Perez con Alvi M-1-2026"
        monkeypatch.setattr(smu.carpetas_mod, "buscar_carpeta_existente_por_rit", lambda rit: None)
        monkeypatch.setattr(smu.carpetas_mod, "crear_carpeta_causa", lambda apellido, empresa, rit: carpeta_causa)
        monkeypatch.setattr(smu.gmail_client, "descargar_adjunto", lambda message_id, attachment_id: b"contenido pdf falso")
        monkeypatch.setattr(smu, "agregar_causa", lambda ruta_excel, datos: {"agregada": True, "fila": 10})
        monkeypatch.setattr(smu.reasoning, "preguntar", lambda tarea, contexto, schema: {"resumen": "Texto de prueba."})

        etiquetas_aplicadas = []
        monkeypatch.setattr(smu.gmail_client, "obtener_o_crear_etiqueta", lambda nombre, color=None: f"label-{nombre}")
        monkeypatch.setattr(smu.gmail_client, "aplicar_etiqueta_a_hilo", lambda thread_id, label_id: etiquetas_aplicadas.append((thread_id, label_id)))

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
