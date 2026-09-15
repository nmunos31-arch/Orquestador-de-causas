import json

import pytest

from gestion_causas import orquestador


class TestCorrerOrquestador:
    def test_corre_goteo_y_devuelve_su_resumen(self, tmp_path):
        ruta_contexto = tmp_path / "_contexto_corrida.json"
        ruta_contexto.write_text(json.dumps({
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(tmp_path / "no_existe.json")},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }), encoding="utf-8")

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
