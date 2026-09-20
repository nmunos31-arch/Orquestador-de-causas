import json
from datetime import datetime, timedelta

from gestion_causas import cache_razonamiento as cache


class TestClave:
    def test_el_mismo_contexto_da_la_misma_clave(self):
        a = cache.clave("tarea", {"mensajes": [{"cuerpo": "hola"}]})
        b = cache.clave("tarea", {"mensajes": [{"cuerpo": "hola"}]})
        assert a == b

    def test_el_orden_de_las_claves_del_dict_no_cambia_la_clave(self):
        a = cache.clave("tarea", {"x": 1, "y": 2})
        b = cache.clave("tarea", {"y": 2, "x": 1})
        assert a == b

    def test_un_mensaje_nuevo_cambia_la_clave(self):
        a = cache.clave("tarea", {"mensajes": [{"cuerpo": "hola"}]})
        b = cache.clave("tarea", {"mensajes": [{"cuerpo": "hola"}, {"cuerpo": "chau"}]})
        assert a != b

    def test_una_tarea_distinta_cambia_la_clave(self):
        assert cache.clave("tarea A", {"x": 1}) != cache.clave("tarea B", {"x": 1})

    def test_un_modelo_distinto_cambia_la_clave(self):
        """Sin esto, cambiar GESTION_CAUSAS_MODELO_CLASIFICACION para comparar
        calidad/costo entre modelos serviría igual la respuesta cacheada del
        modelo viejo hasta por DIAS_VIGENCIA — exactamente el caso de uso
        documentado en reasoning.py para esa variable."""
        a = cache.clave("tarea", {"x": 1}, modelo="claude-haiku-4-5-20251001")
        b = cache.clave("tarea", {"x": 1}, modelo="claude-sonnet-5")
        assert a != b

    def test_modelo_none_y_modelo_vacio_dan_la_misma_clave(self):
        assert cache.clave("tarea", {"x": 1}, modelo=None) == cache.clave("tarea", {"x": 1}, modelo="")


class TestObtenerYGuardar:
    def test_devuelve_lo_guardado(self, tmp_path):
        ruta = tmp_path / "cache.json"
        cache.guardar("abc", {"acuerdo_cerrado": True}, ruta=ruta)
        assert cache.obtener("abc", ruta=ruta) == {"acuerdo_cerrado": True}

    def test_devuelve_none_si_la_clave_no_esta(self, tmp_path):
        assert cache.obtener("no-existe", ruta=tmp_path / "cache.json") is None

    def test_una_entrada_vencida_no_se_devuelve(self, tmp_path):
        ruta = tmp_path / "cache.json"
        viejo = (datetime.now() - timedelta(days=cache.DIAS_VIGENCIA + 1)).isoformat()
        ruta.write_text(
            json.dumps({"abc": {"guardado_en": viejo, "resultado": {"x": 1}}}),
            encoding="utf-8",
        )
        assert cache.obtener("abc", ruta=ruta) is None

    def test_guardar_poda_las_entradas_vencidas(self, tmp_path):
        ruta = tmp_path / "cache.json"
        viejo = (datetime.now() - timedelta(days=cache.DIAS_VIGENCIA + 1)).isoformat()
        ruta.write_text(
            json.dumps({"vieja": {"guardado_en": viejo, "resultado": {"x": 1}}}),
            encoding="utf-8",
        )

        cache.guardar("nueva", {"y": 2}, ruta=ruta)

        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        assert "vieja" not in contenido
        assert "nueva" in contenido


class TestArchivoCorrupto:
    def test_obtener_degrada_a_none_si_el_json_esta_roto(self, tmp_path):
        ruta = tmp_path / "cache.json"
        ruta.write_text('{"abc": {"guardado_en"', encoding="utf-8")
        assert cache.obtener("abc", ruta=ruta) is None

    def test_guardar_reescribe_el_archivo_si_el_json_esta_roto(self, tmp_path):
        ruta = tmp_path / "cache.json"
        ruta.write_text('{"abc": {"guardado_en"', encoding="utf-8")

        cache.guardar("nueva", {"y": 2}, ruta=ruta)

        assert json.loads(ruta.read_text(encoding="utf-8"))["nueva"]["resultado"] == {"y": 2}


class TestEscrituraAtomica:
    def test_guardar_no_deja_un_temporal_atras(self, tmp_path):
        """Mismo patrón que registro._guardar: escribe a un .tmp al lado y
        reemplaza de una sola vez, para que un corte a mitad de la escritura
        no deje el archivo de caché truncado (que _cargar trataría como
        caché vacío, perdiendo TODAS las entradas previas, no solo la que se
        estaba escribiendo)."""
        ruta = tmp_path / "cache.json"
        cache.guardar("abc", {"x": 1}, ruta=ruta)

        assert ruta.exists()
        assert not (tmp_path / "cache.json.tmp").exists()
