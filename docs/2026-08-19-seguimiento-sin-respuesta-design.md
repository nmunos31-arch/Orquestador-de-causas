# Fases 5 y 6: seguimiento de correos sin respuesta y de documentos pendientes

## Contexto

El proyecto "Gestión automática de causas" tiene hoy 4 fases automatizadas (descubrir
causas nuevas, pedir documentos, goteo de documentos, agenda de audiencias). Todas
empujan trabajo *hacia afuera*, pero ninguna vigila lo que queda **colgado**: correos que
Nico manda y nadie contesta, y documentos que pidió y nunca llegaron completos.

Hoy eso se hace de memoria. En la causa Yáñez con SSLL (O-348-2026) se ve el patrón real:
Nico pidió 7 antecedentes el martes 28-jul, no le contestaron, e insistió a mano el lunes
3-ago (exactamente 4 días hábiles después) con *"ruego tener presente los antecedentes
solicitados"*; después la respuesta llegó **parcial** (el punto 3 quedó pendiente y hubo
que perseguirlo tres correos más). Esa persecución manual es la que se automatiza aquí.

Resultado buscado: dos tareas programadas diarias que detecten los casos colgados y dejen
**borradores listos para revisar** (nunca enviados), más un resumen de lo que no alcanza
para borrador.

Las cuatro automatizaciones pedidas se reducen a **dos mecanismos**:

| # | Pedido | Mecanismo |
|---|--------|-----------|
| 1 | Daniela Sánchez no responde en 24 h por una propuesta de acuerdo | Detector "sin respuesta" |
| 4 | Hilos "Causa laboral" iniciados por Nico sin respuesta en 24 h | Detector "sin respuesta" |
| 2 | Documentos pedidos hace 4 días hábiles sin ninguna respuesta | Chequeo "documentos pendientes" |
| 3 | Documentos entregados a medias → recordar los que faltan | Chequeo "documentos pendientes" |

**Daniela = `dsanchezv@smu.cl`** (Daniela Paz Sánchez Vidal, Abogada Senior, Gerencia Legal
Laboral SMU S.A.), verificado en la casilla; ya figura como remitente confiable en la Fase 3.

## Decisiones tomadas con el usuario

- Al detectar falta de respuesta: **avisar y además crear borrador** de insistencia.
- **Dos tareas programadas** separadas (una solo lee, la otra crea borradores).
- Documentos: se recorren **solo las causas del registro local** (`causas-activas`).
- Cadencia de insistencia, **igual para los cuatro casos**: 1ª insistencia al cumplirse el
  umbral (24 h / 4 días hábiles); 2ª a los **2 días hábiles** de la 1ª; después **no se
  generan más borradores**, solo se reporta en el resumen.
- Texto de insistencia por falta de respuesta (autom. 1 y 4), idéntico salvo el nombre:
  ```
  Estimada/o [Nombre]:

  Junto con saludar, ruego tener presente el correo anterior.

  Atentamente,
  ```
- Recordatorio de documentos: **Para** = la persona a quien se le pidieron; **CC** = el
  resto de los participantes del último mensaje, menos Nico.

## Arquitectura

Se respeta la separación que ya rige el paquete: **el CLI hace lo mecánico y
determinístico** (fechas, direcciones, cadencia, JSON a stdout) y **el SKILL.md de la tarea
hace el juicio sobre prosa libre** (¿este correo es una propuesta de acuerdo?, ¿qué
documentos quedaron pendientes?). Ningún módulo nuevo envía ni borra correos — la garantía
por código de `gmail_client.py` se mantiene intacta.

### Módulo nuevo: `gestion_causas/seguimiento.py`

Funciones puras sobre los mensajes ya traídos de Gmail (no llama a la API, así se testea
sin credenciales — mismo criterio que `agenda.py` y `registro.py`):

- `extraer_direccion(remitente)` → `"Nombre <a@b.cl>"` a `"a@b.cl"` en minúsculas.
- `extraer_nombre_pila(remitente)` → `"Alexis Cubillos Arellano <...>"` a `"Alexis"`
  (para el saludo del borrador).
- `parsear_fecha(valor)` → RFC 2822 con `email.utils.parsedate_to_datetime`.
- `normalizar_asunto(asunto)` → quita `Re:`, `RE:`, `RV:`, `Fwd:` repetidos, para poder
  evaluar "el asunto empieza con *Causa laboral*".
- `destinatarios_respuesta(mensaje, direccion_propia)` → `{"para": ..., "cc": [...]}` a
  partir de los headers `From`/`To`/`Cc` del último mensaje, excluyendo la propia dirección.
- `analizar_hilo(mensajes, ahora, direccion_propia, responder_esperado=None)` → dict con
  `iniciado_por`, `ultimo_mensaje_propio`, `ultimo_mensaje`, `horas_sin_respuesta`,
  `hay_respuesta_posterior`, `participantes`. Si se entrega `responder_esperado`, "sin
  respuesta" significa *sin mensaje de esa dirección* posterior al último de Nico (no basta
  con que conteste un tercero — en O-348-2026 contestó Alexis y Daniela seguía muda).

### Cambios en módulos existentes

**`gestion_causas/agenda.py`** — agregar `dias_habiles_entre(desde, hasta, ruta_feriados)`
reusando `cargar_feriados()` y `es_dia_habil()` ya existentes. Caso de prueba tomado de la
realidad: `2026-07-28` → `2026-08-03` debe dar **4**.

**`gestion_causas/registro.py`** — tercer registro JSON, `registro_seguimiento.json`
(agregar al `.gitignore` del paquete junto a los otros dos), con clave `thread_id`:

```json
{
  "19d25c4d7dc4336f": {
    "tipo": "acuerdo-daniela",
    "rit": "O-348-2026",
    "avisos": [{"n": 1, "fecha": "2026-08-19", "draft_id": "r-123", "message_id_origen": "..."}],
    "ultima_revision": "2026-08-19T09:00:00"
  }
}
```

Funciones nuevas: `cargar_registro_seguimiento`, `obtener_seguimiento(thread_id)`,
`registrar_aviso(thread_id, tipo, rit, draft_id, fecha)` y —la clave— la regla de cadencia
en Python, no en prosa:

```python
def puede_insistir(thread_id, hoy=None, ruta=..., ruta_feriados=...) -> dict:
    """{"puede": bool, "n_aviso": int, "motivo": str}
    1er aviso: siempre. 2º: solo si pasaron >= 2 dias habiles desde el 1º.
    3º en adelante: nunca (solo reportar)."""
```

Todas con `ruta` inyectable, como el resto del módulo, para testear con `tmp_path`.

**`gestion_causas/gmail_client.py`** — dos cambios acotados:
1. `leer_mensaje()` devuelve además los headers `to` y `cc` (hoy solo trae `from`), que la
   Fase 6 necesita para armar el "responder a todos".
2. `crear_borrador(..., cc: str | None = None)` → setea `mensaje["cc"]`. No toca nada más;
   sigue sin existir `drafts().send` ni `messages().send`.

**`gestion_causas/cli.py`** — `cmd_leer_hilo` expone también `to`/`cc`, y se agregan los
subcomandos de abajo.

### Subcomandos nuevos del CLI

**`hilos-sin-respuesta`** — el detector mecánico; sirve a las automatizaciones 1, 4 y a la
detección de la 2.

```
python -m gestion_causas.cli hilos-sin-respuesta \
  --query "subject:\"Causa laboral\" newer_than:30d" \
  --horas 24 [--dias-habiles 4] \
  [--iniciado-por nmunoz@gomezyriesco.cl] \
  [--responder-esperado dsanchezv@smu.cl] \
  [--max-hilos 50]
```

Por cada hilo que cumple: `thread_id`, `asunto`, `asunto_normalizado`, `rit` (vía
`registro.extraer_rit`), `empresa` (vía `calendar_client.detectar_empresa`),
`horas_sin_respuesta`, `dias_habiles_sin_respuesta`, `ultimo_mensaje_propio`
(id, fecha, primeros ~400 caracteres del cuerpo para que la IA juzgue de qué se trata) y
`destinatarios` (para/cc sugeridos con el nombre de pila del principal).

**`puede-insistir --thread-id <id> [--hoy AAAA-MM-DD]`** — aplica la cadencia y devuelve
`{"puede": ..., "n_aviso": ..., "motivo": ...}`.

**`registrar-aviso --thread-id <id> --tipo <acuerdo-daniela|causa-laboral|documentos> [--rit] [--draft-id]`**

**`dias-habiles-entre --desde AAAA-MM-DD --hasta AAAA-MM-DD`**

**`crear-borrador`** gana dos flags:
- `--cc "a@x.cl,b@y.cl"`
- `--lista-archivo <ruta.txt>`, que reemplaza la línea `[[LISTA]]` del `--cuerpo-archivo`
  por un `<ol><li>` numerado automáticamente. Hoy `--lista` convierte **todo** el cuerpo en
  lista, lo que no sirve para el texto de la automatización 3, que tiene saludo antes y
  despedida después. Se implementa como `_cuerpo_con_lista(texto, items)` junto a la ya
  existente `_texto_a_lista_html()`, escapando HTML igual que ella.

## Tareas programadas nuevas

### `gestion-causas-sin-respuesta` (Fase 5, diaria)

`C:\Users\usuario\.claude\scheduled-tasks\gestion-causas-sin-respuesta\SKILL.md`, con la
misma estructura que las cuatro existentes (prerrequisito de token, pasos numerados,
resumen final).

1. `diagnostico` — si no autentica contra `nmunoz@gomezyriesco.cl`, detenerse.
2. **Bloque Daniela**: `hilos-sin-respuesta --query "\"Estimada Daniela\" newer_than:30d"
   --horas 24 --responder-esperado dsanchezv@smu.cl`. La búsqueda de Gmail trae ruido
   comprobado (aparecen hilos de "Estimada Patricia"/"Estimada Pamela"), así que la IA
   **confirma leyendo el cuerpo**: que empiece literalmente con "Estimada Daniela" y que
   trate de una **propuesta o bases de acuerdo** (monto propuesto, contrapropuesta, bases
   fijadas por el tribunal). Sin esas dos condiciones, se descarta.
   Nota: el hilo **no** tiene que haber sido iniciado por Nico — normalmente lo inicia SMU
   con la derivación de la demanda.
3. **Bloque "Causa laboral"**: `hilos-sin-respuesta --query "subject:\"Causa laboral\"
   newer_than:30d" --horas 24 --iniciado-por nmunoz@gomezyriesco.cl`. La IA confirma que el
   `asunto_normalizado` **empieza** con "Causa laboral".
4. **Descarte común (evita el falso positivo más frecuente):** si el último mensaje de Nico
   es un acuse de recibo o un cierre de conversación ("Acuso recibo", "Muchas gracias",
   "Lo tenemos presente", "Saludos cordiales" sin pedido), **no** es un correo que espere
   respuesta → se descarta. Si un hilo sale en los dos bloques, se trata una sola vez como
   "acuerdo-daniela".
5. Por cada candidato confirmado: `puede-insistir`. Si `puede` es true, escribe el cuerpo a
   un `.txt` temporal con el texto acordado (`Estimada/o [nombre de pila del destinatario]:`
   / `Junto con saludar, ruego tener presente el correo anterior.` / `Atentamente,`) y
   `crear-borrador --thread-id <id> --destinatario <dirección> --asunto "Re: <asunto>"`.
   Si `creado` es true, `registrar-aviso`. Si `puede` es false porque ya se hicieron los dos
   avisos, va al resumen como "requiere gestión manual".
6. `bitacora` por cada borrador creado, y resumen final: cuántos hilos colgados hay, con
   RIT/empresa/destinatario/días sin respuesta, cuáles quedaron con borrador y cuáles ya
   agotaron los dos avisos.

### `gestion-causas-documentos-pendientes` (Fase 6, diaria)

`C:\Users\usuario\.claude\scheduled-tasks\gestion-causas-documentos-pendientes\SKILL.md`.

1. `diagnostico`.
2. `causas-activas --dias-ventana 60` (mismo universo acotado que usa la Fase 3).
3. Por cada causa: `leer-hilo --thread-id <el del registro>`. Si ahí no aparece ninguna
   solicitud de documentos, `buscar-hilos --query "<rit>"` como respaldo y revisar los
   hilos claramente de la causa — mismo criterio y mismos descartes de reportes
   consolidados que ya documenta la Fase 3 ("Provisiones demanda laborales…", "INFORME
   PROVISIÓN…").
4. La IA identifica en el hilo: (a) el **último mensaje de Nico que pide documentos** (la
   lista numerada que dejó la Fase 2), y (b) qué llegó después. Con
   `dias-habiles-entre --desde <fecha de esa solicitud> --hasta <hoy>` obtiene el plazo.
5. Ramas, mutuamente excluyentes:
   - **Ninguna respuesta de la empresa** y ≥ 4 días hábiles → borrador de insistencia
     (autom. 2), cuerpo exacto:
     ```
     Estimada [Nombre]:

     Junto con saludar, ruego tener presente los documentos solicitados:

     Atentamente,
     ```
   - **Respuesta parcial** (llegaron algunos documentos, faltan otros) → borrador
     recordatorio (autom. 3) con `--lista-archivo`, cuerpo exacto:
     ```
     Estimada [Nombre]:

     Junto con saludar, ruego tener presente que se encuentran pendiente los siguientes documentos:

     [[LISTA]]

     Atentamente,
     ```
     La lista son solo los ítems pendientes, numerados automáticamente por Gmail.
   - **Todo entregado** → nada; no se anota en bitácora para no hacer ruido.
6. Antes de crear cualquiera de los dos: `puede-insistir --thread-id`. Destinatarios según
   lo acordado: `--destinatario` = quien debía enviarlos, `--cc` = el resto del último
   mensaje menos Nico. Luego `registrar-aviso --tipo documentos`.
7. `bitacora` + resumen final: causas revisadas, con solicitud pendiente, borradores
   creados (insistencia vs. recordatorio de faltantes), y las que ya agotaron los dos avisos.

## Archivos

| Archivo | Cambio |
|---|---|
| `gestion_causas/seguimiento.py` | **nuevo** — análisis puro de hilos |
| `gestion_causas/agenda.py` | `dias_habiles_entre()` |
| `gestion_causas/registro.py` | registro de seguimiento + `puede_insistir()` |
| `gestion_causas/gmail_client.py` | `to`/`cc` en `leer_mensaje`, `cc` en `crear_borrador` |
| `gestion_causas/cli.py` | 4 subcomandos nuevos + `--cc`/`--lista-archivo` + `to`/`cc` en `leer-hilo` |
| `gestion_causas/.gitignore` | agregar `registro_seguimiento.json` |
| `tests/test_seguimiento.py` | **nuevo** |
| `tests/test_agenda.py`, `test_registro.py`, `test_gmail_client.py`, `test_cli.py` | casos nuevos |
| `.claude/scheduled-tasks/gestion-causas-sin-respuesta/SKILL.md` | **nuevo** |
| `.claude/scheduled-tasks/gestion-causas-documentos-pendientes/SKILL.md` | **nuevo** |
| `docs/2026-08-19-seguimiento-sin-respuesta-design.md` | **nuevo** — este diseño, versionado en el repo |

## Verificación

**Tests** (mismo estilo de la casa: pytest, stubs manuales encadenados, `tmp_path`, sin red):

```bash
python -m pytest tests/ -q
```

Casos que deben quedar cubiertos:
- `seguimiento`: último mensaje propio vs. ajeno; `responder_esperado` que contestó un
  tercero pero no el esperado; frontera exacta de 24 h; extracción de nombre de pila y de
  dirección; `Re:`/`RV:` anidados en el asunto.
- `agenda.dias_habiles_entre`: 2026-07-28 → 2026-08-03 = 4 (caso real O-348-2026); tramo
  con feriado de por medio.
- `registro.puede_insistir`: 1er aviso siempre; 2º bloqueado antes de 2 días hábiles y
  permitido después; 3º nunca.
- `gmail_client`: el borrador lleva CC; `_cuerpo_con_lista` reemplaza `[[LISTA]]` y escapa
  HTML; **debe seguir pasando el test que prohíbe `drafts().send` / `messages().send` /
  `.trash(`**.
- `cli`: los 4 subcomandos nuevos existen y `--dry-run` no escribe nada.

**Prueba end-to-end en seco**, contra la casilla real pero sin crear nada:

```bash
python -m gestion_causas.cli hilos-sin-respuesta --query "subject:\"Causa laboral\" newer_than:30d" --horas 24 --iniciado-por nmunoz@gomezyriesco.cl
```

```bash
python -m gestion_causas.cli --dry-run crear-borrador --destinatario dsanchezv@smu.cl --cc rgomez@gomezyriesco.cl --asunto "Re: prueba" --cuerpo-archivo cuerpo.txt --lista-archivo faltantes.txt --thread-id 19d25c4d7dc4336f
```

Contraste manual contra un caso conocido: en **O-348-2026** el detector debe reproducir que
la solicitud del 28-jul cumplió 4 días hábiles el 3-ago (fecha en que Nico insistió a mano),
y que tras la respuesta parcial de Alexis quedaba pendiente el punto 3.

**Corrida real supervisada**: ejecutar cada SKILL.md una vez a mano antes de dejarlo
programado, revisar los borradores generados en Gmail sin enviarlos, y recién ahí crear las
dos tareas programadas.
