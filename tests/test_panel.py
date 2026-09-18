import json
from datetime import date
from pathlib import Path

from gestion_causas.panel import (
    acciones_consolidadas,
    estado_causas,
    generar_panel_html,
    pedidos_abiertos_para_panel,
)
from gestion_causas import registro as registro_mod


def _escribir_registro(tmp_path, causas: dict) -> Path:
    ruta = tmp_path / "registro_causas.json"
    ruta.write_text(json.dumps(causas, ensure_ascii=False), encoding="utf-8")
    return ruta


class TestEstadoCausas:
    def test_causa_recien_registrada(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-1-2026": {
                "rit": "M-1-2026", "empresa": "Alvi", "demandante": "Soto",
                "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas == [{
            "rit": "M-1-2026", "empresa": "Alvi", "demandante": "Soto",
            "fase": "Recien registrada", "fecha_audiencia": "",
            "dias_sin_actualizar": 0, "alerta": False,
        }]

    def test_causa_con_demanda_guardada(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-2-2026": {
                "rit": "M-2-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Demanda guardada, en curso"

    def test_causa_con_ofrecimiento(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-3-2026": {
                "rit": "M-3-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "oferta_borrador_creado": True,
                "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Ofrecimiento enviado a Roman"

    def test_causa_con_minuta(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-4-2026": {
                "rit": "M-4-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "oferta_borrador_creado": True,
                "minuta_ejecutada": True, "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Minuta generada"

    def test_causa_con_acuerdo_pendiente_pago(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-5-2026": {
                "rit": "M-5-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "estado_acuerdo": "pendiente_pago",
                "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Acuerdo pendiente de pago"

    def test_causa_con_pago_recibido_pendiente_confirmar(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-6-2026": {
                "rit": "M-6-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "estado_acuerdo": "pago_recibido_pendiente_confirmar",
                "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Pago recibido, pendiente confirmar cierre"

    def test_sin_ultima_actualizacion_da_none(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-8-2026": {"rit": "M-8-2026", "empresa": "Alvi", "demandante": "Soto"},
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["dias_sin_actualizar"] is None
        assert filas[0]["alerta"] is False

    def test_causa_cerrada(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-5-2026": {
                "rit": "M-5-2026", "empresa": "Alvi", "demandante": "Soto",
                "causa_cerrada": True, "ultima_actualizacion": "2026-01-01T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["fase"] == "Cerrada"
        assert filas[0]["alerta"] is False

    def test_alerta_por_dias_sin_actualizar(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-6-2026": {
                "rit": "M-6-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "ultima_actualizacion": "2026-08-01T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["dias_sin_actualizar"] == 26
        assert filas[0]["alerta"] is True

    def test_sin_alerta_dentro_del_umbral(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-7-2026": {
                "rit": "M-7-2026", "empresa": "Alvi", "demandante": "Soto",
                "tiene_demanda": True, "ultima_actualizacion": "2026-08-22T10:00:00",
            }
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert filas[0]["dias_sin_actualizar"] == 5
        assert filas[0]["alerta"] is False

    def test_ordena_por_rit(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-9-2026": {"rit": "M-9-2026", "empresa": "Alvi", "demandante": "B"},
            "M-2-2026": {"rit": "M-2-2026", "empresa": "Alvi", "demandante": "A"},
        })
        filas = estado_causas(hoy=date(2026, 8, 27), ruta=ruta)
        assert [f["rit"] for f in filas] == ["M-2-2026", "M-9-2026"]


class TestGenerarPanelHtml:
    def test_incluye_resumen_de_fases(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        resumen = [
            {"fase": "calendario", "resultado": "No corresponde hoy", "error": None},
            {"fase": "smu", "resultado": "2 causas nuevas", "error": None},
        ]
        contenido = generar_panel_html(resumen, hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "Calendario" in contenido
        assert "No corresponde hoy" in contenido
        assert "2 causas nuevas" in contenido

    def test_marca_errores_de_fase(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        resumen = [{"fase": "goteo", "resultado": None, "error": "token vencido"}]
        contenido = generar_panel_html(resumen, hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "ERROR" in contenido
        assert "token vencido" in contenido

    def test_escapa_html_de_los_datos(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-1-2026": {
                "rit": "M-1-2026", "empresa": "<script>alert(1)</script>",
                "demandante": "Soto", "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        contenido = generar_panel_html([], hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "<script>alert(1)</script>" not in contenido
        assert "&lt;script&gt;" in contenido

    def test_incluye_tabla_de_causas(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {
            "M-1-2026": {
                "rit": "M-1-2026", "empresa": "Alvi", "demandante": "Soto",
                "fecha_audiencia": "2026-09-10", "ultima_actualizacion": "2026-08-27T10:00:00",
            }
        })
        contenido = generar_panel_html([], hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "M-1-2026" in contenido
        assert "10-09-2026" in contenido

    def test_sin_causas_activas_no_falla(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        contenido = generar_panel_html([], hoy=date(2026, 8, 27), ruta_registro=ruta)
        assert "Sin causas activas" in contenido


def _escribir_pedidos(tmp_path, pedidos: dict) -> Path:
    ruta = tmp_path / "registro_pedidos.json"
    ruta.write_text(json.dumps(pedidos, ensure_ascii=False), encoding="utf-8")
    return ruta


def _escribir_seguimiento(tmp_path, seguimiento: dict) -> Path:
    ruta = tmp_path / "registro_seguimiento.json"
    ruta.write_text(json.dumps(seguimiento, ensure_ascii=False), encoding="utf-8")
    return ruta


class TestFilaResumenEstructurado:
    def test_titular_metricas_items_y_notas_se_muestran(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        resumen = [{
            "fase": "goteo",
            "titular": "3 causas con documentos nuevos",
            "metricas": [{"etiqueta": "Causas revisadas", "valor": 27}],
            "items": [{"rit": "O-496-2026", "titulo": "Gonzalez con Rendic", "detalle": "3 documentos nuevos", "etiqueta": "Exhibicion de documentos"}],
            "acciones": [],
            "notas": ["Dominio nuevo visto: @ejemplo.cl"],
        }]
        contenido = generar_panel_html(resumen, hoy=date(2026, 9, 2), ruta_registro=ruta)
        assert "3 causas con documentos nuevos" in contenido
        assert "27" in contenido and "Causas revisadas" in contenido
        assert "O-496-2026" in contenido and "Gonzalez con Rendic" in contenido
        assert "Exhibicion de documentos" in contenido
        assert "Dominio nuevo visto" in contenido

    def test_escapa_html_en_items_y_notas(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        resumen = [{
            "fase": "goteo",
            "titular": "<b>x</b>",
            "items": [{"rit": "<i>M-1</i>", "titulo": "t", "detalle": "d"}],
            "notas": ["<script>alert(1)</script>"],
        }]
        contenido = generar_panel_html(resumen, hoy=date(2026, 9, 2), ruta_registro=ruta)
        assert "<script>alert(1)</script>" not in contenido
        assert "<i>M-1</i>" not in contenido
        assert "&lt;script&gt;" in contenido

    def test_resultado_crudo_se_marca_formato_libre(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        resumen = [{"fase": "smu", "titular": None, "resultado_crudo": "el agente escribio esto en vez de JSON"}]
        contenido = generar_panel_html(resumen, hoy=date(2026, 9, 2), ruta_registro=ruta)
        assert "formato libre" in contenido
        assert "el agente escribio esto en vez de JSON" in contenido

    def test_fallback_resultado_simple_sigue_funcionando(self, tmp_path):
        # Contrato viejo (o fase que respondio "No aplica...") sin campos estructurados.
        ruta = _escribir_registro(tmp_path, {})
        resumen = [{"fase": "calendario", "resultado": "No aplica: solo corre en la corrida de la manana.", "error": None}]
        contenido = generar_panel_html(resumen, hoy=date(2026, 9, 2), ruta_registro=ruta)
        assert "No aplica" in contenido
        assert "formato libre" not in contenido


class TestPedidosAbiertosParaPanel:
    def test_calcula_dias_habiles_faltantes_y_avisos(self, tmp_path):
        ruta_pedidos = _escribir_pedidos(tmp_path, {
            "t1": {
                "thread_id": "t1", "rit": "M-744-2026", "tipo": "documentos",
                "fecha_envio": "2026-08-19", "destinatario": "persona@sb.cl",
                "items_pedidos": ["Contrato", "Finiquito"], "items_recibidos": ["Contrato"],
                "estado": "parcial",
            },
        })
        ruta_seg = _escribir_seguimiento(tmp_path, {
            "t1": {"tipo": "documentos", "rit": "M-744-2026", "avisos": [{"n": 1, "fecha": "2026-08-24", "draft_id": None}]},
        })
        ruta_causas = _escribir_registro(tmp_path, {})
        filas = pedidos_abiertos_para_panel(
            hoy=date(2026, 9, 2), ruta_pedidos=ruta_pedidos, ruta_seguimiento=ruta_seg, ruta_causas=ruta_causas
        )
        assert len(filas) == 1
        assert filas[0]["rit"] == "M-744-2026"
        assert filas[0]["faltan"] == ["Finiquito"]
        assert filas[0]["n_avisos"] == 1
        assert filas[0]["dias_habiles"] > 0

    def test_excluye_completos_y_pendientes_de_envio(self, tmp_path):
        ruta_pedidos = _escribir_pedidos(tmp_path, {
            "t1": {"thread_id": "t1", "rit": "M-1-2026", "estado": "completo"},
            "t2": {"thread_id": "t2", "rit": "M-2-2026", "estado": "pendiente_envio"},
            "t3": {"thread_id": "t3", "rit": "M-3-2026", "estado": "esperando", "fecha_envio": "2026-09-01"},
        })
        ruta_causas = _escribir_registro(tmp_path, {})
        filas = pedidos_abiertos_para_panel(hoy=date(2026, 9, 2), ruta_pedidos=ruta_pedidos, ruta_causas=ruta_causas)
        assert [f["rit"] for f in filas] == ["M-3-2026"]

    def test_excluye_pedido_de_causa_cerrada(self, tmp_path):
        ruta_pedidos = _escribir_pedidos(tmp_path, {
            "t1": {"thread_id": "t1", "rit": "M-1-2026", "estado": "esperando", "fecha_envio": "2026-08-19"},
            "t2": {"thread_id": "t2", "rit": "M-2-2026", "estado": "esperando", "fecha_envio": "2026-08-19"},
        })
        ruta_causas = _escribir_registro(tmp_path, {
            "M-1-2026": {"rit": "M-1-2026", "causa_cerrada": True},
        })
        filas = pedidos_abiertos_para_panel(hoy=date(2026, 9, 2), ruta_pedidos=ruta_pedidos, ruta_causas=ruta_causas)
        assert [f["rit"] for f in filas] == ["M-2-2026"]

    def test_ordena_por_dias_sin_respuesta_descendente(self, tmp_path):
        ruta_pedidos = _escribir_pedidos(tmp_path, {
            "t1": {"thread_id": "t1", "rit": "M-1-2026", "estado": "esperando", "fecha_envio": "2026-08-28"},
            "t2": {"thread_id": "t2", "rit": "M-2-2026", "estado": "esperando", "fecha_envio": "2026-08-19"},
        })
        ruta_causas = _escribir_registro(tmp_path, {})
        filas = pedidos_abiertos_para_panel(hoy=date(2026, 9, 2), ruta_pedidos=ruta_pedidos, ruta_causas=ruta_causas)
        assert [f["rit"] for f in filas] == ["M-2-2026", "M-1-2026"]

    def test_sin_pedidos_abiertos_devuelve_lista_vacia(self, tmp_path):
        ruta_pedidos = _escribir_pedidos(tmp_path, {})
        ruta_causas = _escribir_registro(tmp_path, {})
        assert pedidos_abiertos_para_panel(hoy=date(2026, 9, 2), ruta_pedidos=ruta_pedidos, ruta_causas=ruta_causas) == []


class TestAccionesConsolidadas:
    def test_junta_las_4_fuentes(self):
        resumen = [{"fase": "agenda", "acciones": [{"rit": "M-1-2026", "que": "discrepancia de montos", "urgencia": "media"}]}]
        causas = [{"rit": "M-2-2026", "demandante": "Soto", "fase": "Pago recibido, pendiente confirmar cierre"}]
        pedidos = [{"rit": "M-3-2026", "tipo": "documentos", "estado": "gestion_manual"}]
        borradores = [{"rit": "M-4-2026", "empresa": "Alvi", "demandante": "Perez"}]

        acciones = acciones_consolidadas(resumen, causas, pedidos, borradores)
        rits = {a["rit"] for a in acciones}
        assert rits == {"M-1-2026", "M-2-2026", "M-3-2026", "M-4-2026"}

    def test_ignora_causas_y_pedidos_sin_novedad(self):
        causas = [{"rit": "M-1-2026", "fase": "Demanda guardada, en curso"}]
        pedidos = [{"rit": "M-2-2026", "estado": "esperando"}]
        assert acciones_consolidadas([], causas, pedidos) == []

    def test_no_duplica_pedido_ya_reportado_por_seguimiento(self):
        # La fase `seguimiento` ya reporta en su resumen los pedidos que
        # pasaron a gestion_manual en esta corrida; el barrido de
        # registro_pedidos.json no debe volver a agregarlos.
        resumen = [{
            "fase": "seguimiento",
            "acciones": [{
                "rit": "M-744-2026",
                "que": "2 avisos agotados sin respuesta (documentos) — requiere gestión manual",
                "urgencia": "alta",
            }],
        }]
        pedidos = [{"rit": "M-744-2026", "tipo": "documentos", "estado": "gestion_manual"}]

        acciones = acciones_consolidadas(resumen, [], pedidos)

        assert len([a for a in acciones if a["rit"] == "M-744-2026"]) == 1

    def test_si_reporta_pedido_gestion_manual_de_corrida_anterior(self):
        # Un pedido que paso a gestion_manual en una corrida previa (y por lo
        # tanto no aparece en el resumen de esta corrida) debe seguir
        # apareciendo via el barrido de registro_pedidos.json.
        pedidos = [{"rit": "M-9-2026", "tipo": "acuerdo", "estado": "gestion_manual"}]

        acciones = acciones_consolidadas([], [], pedidos)

        assert [a["rit"] for a in acciones] == ["M-9-2026"]


class TestBandejaAccionesEnPanel:
    def test_sin_acciones_muestra_nada_pendiente(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        # ruta_registro_pedidos/ruta_registro_seguimiento deben aislarse
        # tambien: sin pasarlas, generar_panel_html caia al
        # registro_pedidos.json / registro_seguimiento.json reales del
        # proyecto y el test terminaba viendo acciones pendientes de
        # produccion en vez de "nada pendiente" (bug de aislamiento
        # confirmado el 2026-09-03).
        ruta_pedidos = _escribir_pedidos(tmp_path, {})
        ruta_seg = _escribir_seguimiento(tmp_path, {})
        contenido = generar_panel_html(
            [], hoy=date(2026, 9, 2), ruta_registro=ruta,
            ruta_registro_pedidos=ruta_pedidos, ruta_registro_seguimiento=ruta_seg,
        )
        assert "Nada pendiente de tu parte" in contenido

    def test_con_acciones_las_muestra_arriba_del_resumen(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        ruta_pedidos = _escribir_pedidos(tmp_path, {})
        ruta_seg = _escribir_seguimiento(tmp_path, {})
        resumen = [{"fase": "seguimiento", "titular": "ok", "acciones": [
            {"rit": "M-1-2026", "que": "2 avisos agotados", "urgencia": "alta"},
        ]}]
        contenido = generar_panel_html(
            resumen, hoy=date(2026, 9, 2), ruta_registro=ruta,
            ruta_registro_pedidos=ruta_pedidos, ruta_registro_seguimiento=ruta_seg,
        )
        assert "2 avisos agotados" in contenido
        assert contenido.index("Requiere tu atencion") < contenido.index("Resumen de la corrida")

    def test_borradores_pendientes_aparecen_en_la_bandeja(self, tmp_path):
        ruta = _escribir_registro(tmp_path, {})
        borradores = [{"rit": "M-9-2026", "empresa": "Alvi", "demandante": "Soto"}]
        contenido = generar_panel_html([], hoy=date(2026, 9, 2), ruta_registro=ruta, borradores_pendientes=borradores)
        assert "Borrador de documentos sin enviar" in contenido
        assert "M-9-2026" in contenido
