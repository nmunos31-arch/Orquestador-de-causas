import json

from gestion_causas import uso_tokens


class TestRegistrar:
    def test_agrega_una_linea_json_por_evento(self, tmp_path):
        ruta = tmp_path / "uso.jsonl"

        uso_tokens.registrar({"llamada": "goteo", "input_tokens": 10}, ruta=ruta)
        uso_tokens.registrar({"llamada": "seguimiento", "input_tokens": 20}, ruta=ruta)

        lineas = ruta.read_text(encoding="utf-8").strip().split("\n")
        assert len(lineas) == 2
        assert json.loads(lineas[0])["llamada"] == "goteo"
        assert json.loads(lineas[1])["input_tokens"] == 20

    def test_agrega_timestamp_si_el_evento_no_lo_trae(self, tmp_path):
        ruta = tmp_path / "uso.jsonl"

        uso_tokens.registrar({"llamada": "goteo"}, ruta=ruta)

        evento = json.loads(ruta.read_text(encoding="utf-8").strip())
        assert "momento" in evento

    def test_no_lanza_si_no_se_puede_escribir(self, tmp_path):
        """Telemetría: para cuando se llama acá, la llamada de razonamiento
        ya se pagó. Un disco lleno o una ruta inexistente no puede hacer
        que se pierda su resultado."""
        ruta_imposible = tmp_path / "no" / "existe" / "uso.jsonl"

        uso_tokens.registrar({"llamada": "goteo"}, ruta=ruta_imposible)

        assert not ruta_imposible.exists()


class TestResumen:
    def test_devuelve_totales_en_cero_si_no_existe_el_archivo(self, tmp_path):
        totales = uso_tokens.resumen(ruta=tmp_path / "no-existe.jsonl")
        assert totales["llamadas"] == 0
        assert totales["input_tokens"] == 0

    def test_suma_los_campos_de_todas_las_lineas(self, tmp_path):
        ruta = tmp_path / "uso.jsonl"
        uso_tokens.registrar(
            {"llamada": "goteo.acuerdo_y_pago", "input_tokens": 100, "output_tokens": 5,
             "cache_creation_input_tokens": 10, "cache_read_input_tokens": 20, "costo_usd": 0.01},
            ruta=ruta,
        )
        uso_tokens.registrar(
            {"llamada": "goteo.acuerdo_y_pago", "input_tokens": 50, "output_tokens": 3,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "costo_usd": 0.005},
            ruta=ruta,
        )

        totales = uso_tokens.resumen(ruta=ruta)

        assert totales["llamadas"] == 2
        assert totales["input_tokens"] == 150
        assert totales["output_tokens"] == 8
        assert totales["cache_creation_input_tokens"] == 10
        assert totales["cache_read_input_tokens"] == 20
        assert round(totales["costo_usd"], 3) == 0.015
        assert totales["por_llamada"] == {"goteo.acuerdo_y_pago": 2}

    def test_desde_acota_por_fecha(self, tmp_path):
        ruta = tmp_path / "uso.jsonl"
        uso_tokens.registrar({"llamada": "a", "momento": "2026-09-01T10:00:00"}, ruta=ruta)
        uso_tokens.registrar({"llamada": "b", "momento": "2026-09-20T10:00:00"}, ruta=ruta)

        totales = uso_tokens.resumen(ruta=ruta, desde="2026-09-15")

        assert totales["llamadas"] == 1
        assert totales["por_llamada"] == {"b": 1}

    def test_una_linea_ilegible_se_saltea(self, tmp_path):
        ruta = tmp_path / "uso.jsonl"
        ruta.write_text("no es json\n" + json.dumps({"llamada": "a"}) + "\n", encoding="utf-8")

        totales = uso_tokens.resumen(ruta=ruta)

        assert totales["llamadas"] == 1
