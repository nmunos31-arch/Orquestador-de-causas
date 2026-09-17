import json

from gestion_causas import registro as registro_mod
from gestion_causas.fases import agenda


def _registrar_causa_activa(tmp_path, rit="M-1-2026", **extra):
    ruta_registro = tmp_path / "registro_causas.json"
    datos = {
        "empresa": "Alvi", "demandante": "Perez", "carpeta": str(tmp_path / "Perez con Alvi"),
        "thread_id": "thread-original-1", **extra,
    }
    registro_mod.registrar_causa(rit, datos, ruta=ruta_registro)
    return ruta_registro


def _mapa_audiencias(tmp_path, rit_a_audiencia):
    ruta = tmp_path / "mapa_audiencias.json"
    ruta.write_text(json.dumps({"rit_a_audiencia": rit_a_audiencia}), encoding="utf-8")
    return ruta


def _correr_agenda(contexto, tmp_path, **kwargs):
    kwargs.setdefault("ruta_registro_causas", tmp_path / "registro_causas.json")
    return agenda.correr(contexto, **kwargs)


class TestCorrerSinCausasActivas:
    def test_devuelve_resumen_sin_novedades(self, tmp_path):
        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(tmp_path / "no_existe.json")}}
        resumen = _correr_agenda(contexto, tmp_path)

        assert resumen == {
            "fase": "agenda",
            "titular": "Sin causas activas para revisar agenda",
            "metricas": [],
            "items": [],
            "acciones": [],
            "notas": [],
        }


class TestResolucionDeAudiencia:
    def test_causa_sin_evento_en_el_mapa_se_cuenta_como_sin_evento(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {})

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path)

        metrica = next(m for m in resumen["metricas"] if m["etiqueta"] == "Sin evento de calendario todavía")
        assert metrica["valor"] == 1
        assert resumen["items"] == []
        assert resumen["acciones"] == []

    def test_causa_con_tipo_ambiguo_se_anota_en_notas_y_no_genera_nada(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {
            "M-1-2026": {"fecha": "2026-10-01", "resumen": "Reunión rara", "tipo": "Ambiguo"},
        })

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path)

        assert len(resumen["notas"]) == 1
        assert "M-1-2026" in resumen["notas"][0]["detalle"]
        assert resumen["items"] == []

    def test_metricas_incluyen_causas_revisadas_y_borradores_creados(self, tmp_path):
        _registrar_causa_activa(tmp_path)
        ruta_mapa = _mapa_audiencias(tmp_path, {})

        contexto = {"fecha_hoy": "2026-09-17", "mapa_audiencias": {"ruta": str(ruta_mapa)}}
        resumen = _correr_agenda(contexto, tmp_path)

        etiquetas = [m["etiqueta"] for m in resumen["metricas"]]
        assert etiquetas == ["Causas revisadas", "Borradores de ofrecimiento creados", "Sin evento de calendario todavía"]
