import json

from gestion_causas import mapas


class TestLeerMapaAudiencias:
    def test_lee_el_mapa_desde_la_ruta_del_contexto(self, tmp_path):
        ruta = tmp_path / "mapa_audiencias.json"
        ruta.write_text(json.dumps({
            "rit_a_audiencia": {"M-1-2026": {"fecha": "2026-10-01", "resumen": "Audiencia única", "tipo": "Única"}},
        }), encoding="utf-8")

        contexto = {"mapa_audiencias": {"ruta": str(ruta)}}

        resultado = mapas.leer_mapa_audiencias(contexto)

        assert resultado["rit_a_audiencia"]["M-1-2026"]["tipo"] == "Única"

    def test_devuelve_mapa_vacio_si_no_hay_ruta_en_el_contexto(self):
        assert mapas.leer_mapa_audiencias({}) == {"rit_a_audiencia": {}}

    def test_devuelve_mapa_vacio_si_el_archivo_no_existe(self, tmp_path):
        contexto = {"mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")}}
        assert mapas.leer_mapa_audiencias(contexto) == {"rit_a_audiencia": {}}
