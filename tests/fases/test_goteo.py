from gestion_causas.fases import goteo


class TestCorrerSinCausasActivas:
    def test_devuelve_resumen_sin_novedades(self, tmp_path):
        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(tmp_path / "no_existe.json")},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = goteo.correr(
            contexto,
            ruta_registro_causas=tmp_path / "registro_causas.json",
            ruta_registro_ceco=tmp_path / "registro_ceco.json",
        )

        assert resumen["fase"] == "goteo"
        assert resumen["titular"] == "Sin causas activas para revisar"
        assert resumen["items"] == []
        assert resumen["acciones"] == []
