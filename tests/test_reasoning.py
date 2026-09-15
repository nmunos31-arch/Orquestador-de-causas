import json
import subprocess

from gestion_causas.reasoning import preguntar


SCHEMA_SIMPLE = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}


class TestPreguntar:
    def test_devuelve_json_parseado_cuando_la_respuesta_es_valida(self):
        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            return json.dumps({"ok": True})

        resultado = preguntar("tarea de prueba", {"dato": 1}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert resultado == {"ok": True}
        assert len(llamadas) == 1
        assert "tarea de prueba" in llamadas[0]
        assert '"dato": 1' in llamadas[0]

    def test_ignora_bloque_de_codigo_markdown(self):
        def ejecutar_falso(prompt):
            return "```json\n" + json.dumps({"ok": True}) + "\n```"

        resultado = preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)
        assert resultado == {"ok": True}

    def test_reintenta_una_vez_si_la_primera_respuesta_no_es_json(self):
        llamadas = []

        def ejecutar_falso(prompt):
            llamadas.append(prompt)
            if len(llamadas) == 1:
                return "esto no es JSON"
            return json.dumps({"ok": True})

        resultado = preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert resultado == {"ok": True}
        assert len(llamadas) == 2
        assert "no era JSON válido" in llamadas[1]

    def test_devuelve_error_si_falla_dos_veces(self):
        def ejecutar_falso(prompt):
            return "esto tampoco es JSON"

        resultado = preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert "error" in resultado
        assert isinstance(resultado["error"], str)

    def test_devuelve_error_en_vez_de_propagar_si_ejecutar_lanza_excepcion(self):
        def ejecutar_falso(prompt):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=120)

        resultado = preguntar("tarea", {}, SCHEMA_SIMPLE, ejecutar=ejecutar_falso)

        assert "error" in resultado
        assert isinstance(resultado["error"], str)
