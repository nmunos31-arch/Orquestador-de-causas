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
