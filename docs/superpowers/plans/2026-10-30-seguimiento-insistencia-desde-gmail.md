# Seguimiento: insistencia basada en lo realmente enviado — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la fase "seguimiento" decida insistencias a partir de lo que Nico de verdad envió en Gmail (no de los borradores que el bot creó), que los borradores queden bien integrados a la cadena, y corregir los bugs de detección encontrados en el diagnóstico.

**Architecture:** `gmail_client` aplana mensajes marcando borradores (`es_borrador`) y hora exacta; funciones puras nuevas en `gestion_causas/seguimiento.py` filtran "enviados propios" y arman el bloque citado; `fases/seguimiento.py` reconstruye en cada corrida los avisos desde los enviados reales del hilo (registro_seguimiento pasa a ser un reflejo, no la fuente de verdad).

**Tech Stack:** Python 3, Gmail API (googleapiclient), pytest con monkeypatch (patrón de `tests/fases/test_seguimiento.py`), `zoneinfo("America/Santiago")` (disponible).

**Spec:** diagnóstico de esta conversación (fallas 1–8 + menores). Al aprobar, este plan se copia a `docs/superpowers/plans/2026-10-30-seguimiento-insistencia-desde-gmail.md` y se commitea con la Tarea 1.

## Contexto

Hoy un aviso de insistencia se cuenta al **crear** el borrador (`registrar_aviso` en `fases/seguimiento.py:274`), nunca se verifica si se envió. Consecuencias: borrador borrado = aviso contado; insistencia escrita a mano = invisible (el bot insiste encima); borrador de documentos borrado = se toma un mensaje propio viejo como "enviado" o se descarta para siempre si se reescribió como correo nuevo. Además `leer_hilo` no distingue borradores de enviados, el borrador no trae historial citado y su CC suma a todos los participantes históricos, una respuesta del mismo día nunca cuenta, pedidos sin lista de ítems se autocierran, y un hilo re-etiquetado no se reabre.

## Global Constraints

- El código **nunca envía ni borra** correos (tests existentes en `tests/test_gmail_client.py` lo vigilan: no agregar `send`/`delete`).
- Cuenta propia: `CUENTA_TRABAJO = "nmunoz@gomezyriesco.cl"`; zona horaria de negocio: `America/Santiago`.
- Cadencia vigente de `registro.puede_insistir` no cambia (1º siempre; 2º ≥2 hábiles; 3º+ por tier de audiencia). Solo cambia *de dónde salen* los avisos.
- Textos de los borradores (texto A / texto B) no cambian salvo saludo y bloque citado.
- Comentarios/docstrings en español, mismo estilo y densidad que el archivo.
- Tests: `python -m pytest -q` en verde al final de cada tarea.

## Review Focus

1. Pedidos legados sin `momento_envio` ni `message_id` en el hilo → deben seguir funcionando (fallback a `fecha_envio` 00:00 America/Santiago), no romper ni insistir de inmediato. → test en Tarea 2.
2. Primera corrida tras el cambio: `registro_seguimiento.json` con avisos inflados (O-173, O-348 con 5 avisos) → los avisos se recalculan a lo realmente enviado; el contador puede bajar y eso es correcto. → test en Tarea 4.
3. Hilo cuyo último mensaje es un borrador de Nico → `In-Reply-To`/`References` deben salir del último mensaje **no borrador**. → test en Tarea 1.
4. Correo de pedido HTML sin parte text/plain → el bloque citado no debe mostrar etiquetas crudas. → test en Tarea 5.
5. `mapa_hilos` generado por una versión anterior (mensajes sin `es_borrador`) → tratar ausencia como `False`, sin KeyError. → test en Tarea 2.

---

### Tarea 1: Aplanado único de mensajes con marca de borrador

**Files:**
- Modify: `gestion_causas/gmail_client.py` (`leer_hilo`, `cabeceras_respuesta_de_hilo`, `listar_borradores_de_hilo`)
- Modify: `gestion_causas/cli.py` (`cmd_leer_hilo` :83, `_mensajes_de_hilo` :345 → usan el helper)
- Test: `tests/test_gmail_client.py`

**Interfaces:**
- Produces: `gmail_client.aplanar_mensaje(mensaje_crudo: dict) -> dict` — mismas claves que hoy (`id, thread_id, subject, sender, to, cc, date, cuerpo_texto, adjuntos`) + `labels: list[str]`, `es_borrador: bool` (`"DRAFT" in labelIds`), `message_id_header: str` (header Message-ID, case-insensitive, `""` si falta).

- [ ] **Step 1: Tests que fallan**
  - `test_aplanar_mensaje_marca_borrador`: crudo con `labelIds=["DRAFT"]` → `es_borrador is True`; con `["SENT"]` → `False`; sin `labelIds` → `False`.
  - `test_cabeceras_respuesta_ignora_borrador_final`: hilo fake metadata con 2 mensajes, el último con `labelIds=["DRAFT"]` y Message-ID `<draft@x>` → `in_reply_to == "<real@x>"` (el del penúltimo).
  - `test_listar_borradores_de_hilo_solo_pide_detalle_de_los_del_hilo`: fake `drafts().list` devuelve 3 drafts con `message.threadId` `t1, t2, t1` → resultado tiene 2 detalles y `drafts().get` se llamó exactamente 2 veces.
- [ ] **Step 2:** `python -m pytest tests/test_gmail_client.py -q` → FAIL.
- [ ] **Step 3:** Implementar `aplanar_mensaje`; `leer_hilo` y los dos de `cli.py` lo usan (elimina las 3 copias). En `cabeceras_respuesta_de_hilo` pedir también `labelIds` (vienen por defecto en `format="metadata"`) y tomar el último mensaje sin `DRAFT`. En `listar_borradores_de_hilo` filtrar por `borrador["message"]["threadId"]` del `drafts.list` **antes** de llamar `drafts.get` (mantiene el formato de retorno que usan `agenda.py:370` y `smu.py:393`).
- [ ] **Step 4: Verificación real (solo lectura):** con un hilo que tenga un borrador abierto, `python -c "from gestion_causas import gmail_client as g; print([(m['subject'], m['es_borrador']) for m in g.leer_hilo('<thread_id>')])"` → confirma que el borrador aparece con `es_borrador=True`. Si **no** aparece, anotarlo en el plan (la falla 3 queda descartada, el resto sigue igual).
- [ ] **Step 5:** `python -m pytest -q` → PASS. Commit `fix(gmail_client): marca borradores al aplanar hilos y no los usa como cabecera de respuesta` (incluye copia del plan en `docs/superpowers/plans/`).

### Tarea 2: Funciones puras de "enviados propios" y hora exacta

**Files:**
- Modify: `gestion_causas/seguimiento.py`
- Test: `tests/test_seguimiento.py`

**Interfaces:**
- Consumes: claves `es_borrador`, `date`, `sender` de Tarea 1.
- Produces:
  - `momento(mensaje: dict) -> datetime` (aware, vía `parsear_fecha`).
  - `momento_desde_fecha(fecha_iso: str) -> datetime` → `AAAA-MM-DD 00:00` en `America/Santiago`.
  - `enviados_propios(mensajes: list, direccion_propia: str, desde: datetime | None = None) -> list[dict]` — remitente == propia, `not m.get("es_borrador")`, `momento(m) > desde` si se entrega; ordenados por momento.
  - `extraer_items_lista(cuerpo_texto: str) -> list[str]` — líneas `^\s*(\d+[.)]|[-*])\s+(.+)` → texto del ítem (mismo regex que hoy usa `_pedidos_desde_etiqueta` para `tiene_lista`).

- [ ] **Step 1: Tests que fallan:** `test_enviados_propios_excluye_borradores_y_ajenos`; `test_enviados_propios_filtra_por_momento_estricto` (mensaje 10:00 vs `desde` 09:00 mismo día → incluido); `test_enviados_propios_sin_clave_es_borrador_cuenta_como_enviado` (Review Focus 5); `test_momento_desde_fecha_usa_santiago` (`.utcoffset()` ∈ {-3h, -4h}); `test_extraer_items_lista` (`"1. Contrato\n2) Finiquito\n- EERR\ntexto"` → `["Contrato", "Finiquito", "EERR"]`).
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(seguimiento): helpers de enviados propios y hora exacta`.

### Tarea 3: Respuestas posteriores por hora exacta, sin borradores ni mensajes propios

**Files:**
- Modify: `gestion_causas/fases/seguimiento.py` (`_mensajes_posteriores` :103, `_procesar_pedido` :285, `_verificar_borradores_pendientes` y `_pedidos_desde_etiqueta` para guardar `momento_envio`)
- Test: `tests/fases/test_seguimiento.py`

**Interfaces:**
- Consumes: `momento`, `momento_desde_fecha`, `enviados_propios` (Tarea 2).
- Produces: `_momento_envio(pedido: dict, mensajes_hilo: list) -> datetime` — prioridad: `pedido["momento_envio"]` (ISO) → momento del mensaje con `id == pedido["message_id"]` en el hilo → `momento_desde_fecha(pedido["fecha_envio"])`. Nuevo campo de pedido `momento_envio: str` (ISO con offset) al dar de alta.
- `_mensajes_posteriores(thread_id, mensajes_hilo, momento_envio: datetime, rit, mapa_hilos) -> list[dict]` (cambia el 3er parámetro de `str` a `datetime`): excluye `es_borrador` y remitente `CUENTA_TRABAJO`.

- [ ] **Step 1: Tests que fallan:** `test_respuesta_del_mismo_dia_cuenta` (envío 09:00, respuesta 15:00 mismo día → 1 posterior); `test_excluye_borradores_y_mensajes_propios`; `test_momento_envio_pedido_legado_sin_message_id` (Review Focus 1: solo `fecha_envio` → 00:00 Santiago); actualizar los 2 tests existentes de `TestMensajesPosteriores` a la nueva firma.
- [ ] **Step 2:** FAIL. **Step 3:** implementar; las altas (`_verificar_borradores_pendientes`, `_pedidos_desde_etiqueta`) guardan `momento_envio = momento(ultimo_propio).isoformat()`. **Step 4:** PASS.
- [ ] **Step 5:** Commit `fix(seguimiento): respuestas del mismo dia cuentan y se ignoran borradores/propios`.

### Tarea 4: Avisos reconstruidos desde lo enviado + borrador pendiente visible

**Files:**
- Modify: `gestion_causas/registro.py` (nueva función; `puede_insistir` intacto)
- Modify: `gestion_causas/fases/seguimiento.py` (`_evaluar_insistencia` :226, `_crear_insistencia` :170, `_crear_recordatorio_faltantes` :190)
- Test: `tests/test_registro.py`, `tests/fases/test_seguimiento.py`

**Interfaces:**
- Consumes: `enviados_propios`, `_momento_envio`.
- Produces:
  - `registro.sincronizar_avisos(thread_id: str, avisos_enviados: list[dict], tipo: str, rit: str | None, borrador_pendiente: dict | None, ruta=RUTA_REGISTRO_SEGUIMIENTO) -> dict` — reemplaza `entrada["avisos"]` por `[{"n", "fecha", "message_id"}]` (fecha = día Santiago del envío) y guarda/limpia `entrada["borrador_pendiente"] = {"draft_id", "fecha"}`.
  - `_borradores_del_hilo(mensajes_hilo: list) -> list[dict]` — mensajes con `es_borrador`. Reemplaza las llamadas a `gmail_client.listar_borradores_de_hilo` en esta fase.

- [ ] **Step 1: Tests que fallan:**
  - `test_borrador_borrado_no_cuenta_como_aviso`: registro con 1 aviso viejo, hilo sin enviados propios posteriores → tras sincronizar `avisos == []` y `puede_insistir` da `n_aviso == 1`.
  - `test_insistencia_manual_cuenta_como_aviso`: hilo con un enviado propio posterior al pedido (sin borrador del bot) del día anterior → no se crea borrador (2º aviso exige 2 hábiles), resultado `"sin_novedad"`.
  - `test_avisos_inflados_se_recalculan` (Review Focus 2): 5 avisos en registro, 2 enviados reales → quedan 2.
  - `test_borrador_pendiente_genera_accion`: hilo con `es_borrador` propio y `borrador_pendiente.fecha` hace ≥2 días hábiles → `acciones` trae `"Insistencia pendiente de enviar hace N días hábiles"` urgencia `"media"`, no se crea otro borrador.
  - `test_no_duplica_si_ya_hay_borrador_en_la_cadena` (existente) adaptado a `es_borrador` en `mensajes_hilo` en vez de monkeypatch de `listar_borradores_de_hilo`.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** En `_evaluar_insistencia`, antes de `puede_insistir`: avisos = `enviados_propios(mensajes_hilo, CUENTA_TRABAJO, desde=_momento_envio(...))` excluyendo el `message_id` del pedido; llamar `sincronizar_avisos`. Al crear un borrador, registrar solo `borrador_pendiente` (dejar de llamar `registrar_aviso` aquí; la función queda para `cli.cmd_registrar_aviso`). `items` sigue informando "Nº aviso de insistencia" con `cadencia["n_aviso"]`.
- [ ] **Step 4:** PASS. **Step 5:** Commit `fix(seguimiento): la cadencia cuenta correos enviados, no borradores creados`.

### Tarea 5: Borrador integrado a la cadena (citado, destinatarios, saludo)

**Files:**
- Modify: `gestion_causas/seguimiento.py` (helper de citado)
- Modify: `gestion_causas/fases/seguimiento.py` (`_destinatarios_pedido` :127, `_nombre_para_saludo` :121, `_crear_insistencia`, `_crear_recordatorio_faltantes`)
- Test: `tests/test_seguimiento.py`, `tests/fases/test_seguimiento.py`

**Interfaces:**
- Produces: `seguimiento.bloque_citado_html(mensaje: dict) -> str` — `<br><div class="gmail_quote"><div class="gmail_attr">El {fecha dd-mm-aaaa HH:MM}, {sender} escribió:</div><blockquote class="gmail_quote" style="margin:0 0 0 .8ex;border-left:1px #ccc solid;padding-left:1ex">{cuerpo}</blockquote></div>`; `cuerpo` = `cuerpo_texto` con etiquetas HTML quitadas si las trae, escapado, saltos → `<br>`.
- `_destinatarios_pedido(pedido, mensajes_hilo) -> {"para": str, "cc": str}`: Para = `pedido["destinatario"]` o el del último enviado propio; CC = To+Cc del **último enviado propio** (vía `destinatarios_de_ultimo_propio`) sin Para ni Nico. Ya no suma participantes históricos.
- `_nombre_para_saludo(pedido, mensajes_hilo) -> str`: nombre visible del Para en el To del último enviado propio con `extraer_nombre_pila`; fallback a la parte local actual.

- [ ] **Step 1: Tests que fallan:** `test_bloque_citado_escapa_y_cita` (cuerpo con `<script>` sale escapado); `test_bloque_citado_quita_etiquetas_html` (Review Focus 4: `"<p>Hola</p>"` → contiene `Hola`, no `&lt;p&gt;`); `test_cc_sale_del_ultimo_enviado_propio` (un participante viejo que no está en el último propio no aparece); `test_saludo_usa_nombre_visible` (`"Daniela Sánchez <dsanchezv@smu.cl>"` → `"Daniela"`); `test_borrador_incluye_bloque_citado` (monkeypatch `crear_borrador` captura cuerpo → contiene `gmail_quote`). Ajustar `TestNombreParaSaludo` existente a la nueva firma.
- [ ] **Step 2:** FAIL. **Step 3:** implementar; citar el último mensaje no borrador del hilo. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(seguimiento): borradores de insistencia citan la cadena y responden a los mismos destinatarios`.

### Tarea 6: Detección robusta del envío del borrador de documentos

**Files:**
- Modify: `gestion_causas/fases/smu.py` (:417 guarda `borrador_documentos_creado`)
- Modify: `gestion_causas/fases/seguimiento.py` (`_verificar_borradores_pendientes` :403)
- Test: `tests/fases/test_seguimiento.py`, `tests/fases/test_smu.py`

**Interfaces:**
- Produces: campos de causa `borrador_documentos_creado: str` (ISO) y `borrador_documentos_buscar_envio_desde: str` (ISO) — este último marca "borrador desaparecido sin envío detectado".
- `_buscar_envio_fuera_del_hilo(causa: dict, desde: datetime) -> tuple[str, dict] | None` — `gmail_client.buscar_hilos(f'in:sent after:{AAAA/MM/DD} ("{rit}" OR subject:"{asunto normalizado del hilo de la causa}")')`, lee cada hilo y devuelve `(thread_id, mensaje)` del primer `enviados_propios(..., desde=desde)`.

- [ ] **Step 1: Tests que fallan:**
  - `test_mensaje_propio_anterior_al_borrador_no_cuenta_como_envio`: draft desaparecido, hilo con mensaje propio de antes de `borrador_documentos_creado` → no se crea pedido; queda `borrador_documentos_buscar_envio_desde`.
  - `test_reescrito_como_correo_nuevo_se_detecta`: búsqueda fake devuelve otro hilo con envío propio posterior → pedido registrado con **ese** `thread_id`, `origen: "borrador_enviado"`, items de `documentos_solicitados`.
  - `test_sin_envio_detectado_avisa_y_sigue_buscando`: ni hilo ni búsqueda → `acciones` trae "Borrador de documentos de {rit} ya no está y no se detectó el envío — revisar" (urgencia `"media"`); en la corrida siguiente vuelve a buscar (por `buscar_envio_desde`) y al encontrarlo limpia el campo.
  - Legado sin `borrador_documentos_creado`: usa `primera_vez_registrada` de la causa como `desde`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar; `causas_con_borrador_pendiente` también devuelve causas con `borrador_documentos_buscar_envio_desde` (o función hermana en `registro.py`). **Step 4:** PASS.
- [ ] **Step 5:** Commit `fix(seguimiento): no confunde borrador borrado con enviado y detecta reenvio en correo nuevo`.

### Tarea 7: Pedidos sin ítems y reapertura por etiqueta

**Files:**
- Modify: `gestion_causas/fases/seguimiento.py` (`_pedidos_desde_etiqueta` :445, `_procesar_pedido` :335-346, `_clasificar_pedido` :48)
- Modify: `gestion_causas/registro.py` (`migrar_pedidos_bootstrap`: marcar `descartado` los `pendiente_envio` cuyo draft ya no está en ninguna causa)
- Test: `tests/fases/test_seguimiento.py`, `tests/test_registro.py`

**Interfaces:**
- Consumes: `extraer_items_lista`, `enviados_propios`, `_momento_envio`.
- `_clasificar_pedido` agrega al contexto `cuerpo_pedido` (texto del mensaje `message_id`, ≤2000 chars).

- [ ] **Step 1: Tests que fallan:**
  - `test_alta_por_etiqueta_extrae_items`: cuerpo con lista numerada → `items_pedidos` poblado.
  - `test_parcial_sin_items_no_cierra`: `items_pedidos == []`, clasificación `parcial` → estado sigue `esperando`, `acciones` trae "Respuesta parcial a pedido sin lista de documentos — revisar", sin recordatorio.
  - `test_reetiquetado_reabre_pedido_cerrado`: pedido `completo` + hilo con enviado propio posterior a su `momento_envio` + etiqueta → estado `esperando`, nuevo `message_id`/`momento_envio`, `items_recibidos == []` (los avisos se resetean solos por Tarea 4).
  - `test_bootstrap_descarta_pendiente_envio_huerfano`.
- [ ] **Step 2:** FAIL. **Step 3:** implementar. **Step 4:** PASS.
- [ ] **Step 5:** Commit `fix(seguimiento): pedidos sin lista no se autocierran y el reetiquetado reabre`.

---

## Verificación end-to-end

1. `python -m pytest -q` en verde.
2. Corrida real de la fase en seco sobre Gmail de trabajo (solo crea borradores, nunca envía): ejecutar el ciclo como hoy y revisar en el resultado de la fase: avisos de O-173-2026 / O-348-2026 recalculados a lo enviado; ninguna insistencia nueva en hilos donde Nico ya insistió a mano; acciones de "borrador pendiente" y "borrador desaparecido".
3. Abrir en Gmail un borrador de insistencia nuevo: aparece dentro de la cadena, con historial citado, Para/CC iguales al último correo de Nico y saludo con nombre real.
4. Diff de `registro_seguimiento.json` antes/después revisado con Nico antes de commitear datos.
