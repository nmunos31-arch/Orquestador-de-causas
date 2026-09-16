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
