import json

import pytest

from gestion_causas import orquestador


class TestCorrerOrquestador:
    def test_corre_goteo_y_devuelve_su_resumen(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(tmp_path / "no_existe.json")},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }), encoding="utf-8")

        monkeypatch.setattr(orquestador.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["goteo"]["fase"] == "goteo"
        assert resultado["fases"]["goteo"]["titular"] == "Sin causas activas para revisar"

    def test_falla_de_una_fase_no_interrumpe_el_resultado(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-15"}), encoding="utf-8")

        def goteo_falla(contexto_corrida, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(orquestador.fases_goteo, "correr", goteo_falla)
        monkeypatch.setattr(orquestador.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["goteo"]["fase"] == "goteo"
        assert "boom" in resultado["fases"]["goteo"]["error"]

    def test_falla_si_no_existe_el_contexto_de_corrida(self, tmp_path):
        ruta_contexto = tmp_path / "no_existe.json"

        with pytest.raises(FileNotFoundError):
            orquestador.correr(ruta_contexto=ruta_contexto)


class TestOrquestadorDespachaSmu:
    def test_corre_smu_y_devuelve_su_resumen(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-16"}), encoding="utf-8")

        monkeypatch.setattr(orquestador.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["smu"]["fase"] == "smu"
        assert resultado["fases"]["smu"]["titular"] == "Sin correos nuevos"

    def test_smu_recibe_ruta_registro_ceco(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-16"}), encoding="utf-8")

        llamadas = []
        monkeypatch.setattr(orquestador.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])
        monkeypatch.setattr(orquestador.fases_smu, "correr", lambda *a, **k: llamadas.append(k) or {"fase": "smu"})

        orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert llamadas[0]["ruta_registro_ceco"] == tmp_path / "registro_ceco.json"


class TestOrquestadorDespachaAgenda:
    def test_corre_agenda_y_devuelve_su_resumen(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({"fecha_hoy": "2026-09-17"}), encoding="utf-8")

        monkeypatch.setattr(orquestador.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["agenda"]["fase"] == "agenda"
        assert resultado["fases"]["agenda"]["titular"] == "Sin causas activas para revisar agenda"


class TestOrquestadorDespachaSeguimientoYCalendarioSoloEnLaManana:
    def test_no_despacha_seguimiento_ni_calendario_fuera_de_la_manana(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(
            json.dumps({"fecha_hoy": "2026-09-18", "corrida": "resto"}), encoding="utf-8"
        )
        monkeypatch.setattr(orquestador.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        resultado = orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert "seguimiento" not in resultado["fases"]
        assert "calendario" not in resultado["fases"]

    def test_despacha_seguimiento_y_calendario_en_la_manana(self, tmp_path, monkeypatch):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(
            json.dumps({"fecha_hoy": "2026-09-21", "corrida": "manana", "es_lunes": True}), encoding="utf-8"
        )
        monkeypatch.setattr(orquestador.fases_smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])
        monkeypatch.setattr(orquestador.fases_seguimiento, "correr", lambda *a, **k: {"fase": "seguimiento"})
        monkeypatch.setattr(orquestador.fases_calendario, "correr", lambda *a, **k: {"fase": "calendario"})

        resultado = orquestador.correr(
            ruta_contexto=ruta_contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resultado["fases"]["seguimiento"]["fase"] == "seguimiento"
        assert resultado["fases"]["calendario"]["fase"] == "calendario"
