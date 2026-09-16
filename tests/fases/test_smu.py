from gestion_causas.fases import smu


class TestCorrerSinHilosNuevos:
    def test_devuelve_resumen_sin_novedades(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smu.gmail_client, "buscar_hilos", lambda query, max_resultados=50: [])

        contexto = {"fecha_hoy": "2026-09-16"}

        resumen = smu.correr(contexto, ruta_registro_causas=tmp_path / "registro_causas.json")

        assert resumen["fase"] == "smu"
        assert resumen["titular"] == "Sin correos nuevos"
        assert resumen["items"] == []
