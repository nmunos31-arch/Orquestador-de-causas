import json

from gestion_causas import registro as registro_mod
from gestion_causas.fases import goteo


def _registrar_causa_activa(tmp_path, rit="M-1-2026", **extra):
    ruta_registro = tmp_path / "registro_causas.json"
    datos = {
        "empresa": "Alvi", "demandante": "Perez", "carpeta": str(tmp_path / "Perez con Alvi"),
        "thread_id": "thread-original-1", **extra,
    }
    registro_mod.registrar_causa(rit, datos, ruta=ruta_registro)
    return ruta_registro


def _mapa_hilos_vacio(tmp_path):
    ruta = tmp_path / "mapa_hilos.json"
    ruta.write_text(json.dumps({"rit_a_hilos": {}, "hilos": {}}), encoding="utf-8")
    return ruta


def _correr_goteo(contexto, tmp_path, **kwargs):
    kwargs.setdefault("ruta_registro_causas", tmp_path / "registro_causas.json")
    kwargs.setdefault("ruta_registro_ceco", tmp_path / "registro_ceco.json")
    return goteo.correr(contexto, **kwargs)


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


class TestCorrerCausaSinNovedades:
    def test_causa_activa_sin_hilos_en_el_mapa_no_genera_items(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_hilos_vacio(tmp_path)

        contexto = {
            "fecha_hoy": "2026-09-15",
            "mapa_hilos": {"ruta": str(ruta_mapa)},
            "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")},
        }

        resumen = _correr_goteo(contexto, tmp_path)

        assert resumen["items"] == []
        assert any(m["etiqueta"] == "Causas revisadas" and m["valor"] == 1 for m in resumen["metricas"])
