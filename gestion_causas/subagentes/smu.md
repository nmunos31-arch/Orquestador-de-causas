# Subagente "smu" (Fases 1-2) del orquestador gestion-causas-orquestador

> **⚠️ ARCHIVO HISTÓRICO — YA NO SE EJECUTA (desde 2026-09-XX, migración a
> `ciclo.py`).** El ciclo automatizado (`python -m gestion_causas.ciclo`, disparado por
> la tarea programada) corre esta fase con código Python puro en
> `gestion_causas/fases/smu.py` — ya no despacha un subagente de Claude que lea este
> prompt paso a paso. Este `.md` queda solo como referencia histórica del diseño y las
> reglas de negocio acordadas con el usuario (regla de origen de la cadena, excepción de
> Román, plantilla del cuadro-resumen, etc.), muchas de las cuales siguen vigentes en el
> código nuevo. **Si necesitás cambiar el comportamiento real de la fase smu (por
> ejemplo la query de búsqueda de correos), editá `fases/smu.py`, no este archivo** — un
> cambio hecho solo acá no tiene ningún efecto en las corridas automáticas (así se
> descubrió el 2026-09-25: la query de este archivo se corrigió primero acá por error,
> sin efecto real, hasta notar que la query vigente vivía hardcodeada en `fases/smu.py`).

Fases 1 y 2 del proyecto "Gestión automática de causas nuevas desde la casilla del
trabajo" — ver el diseño completo en
`C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md` y en
`Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md`. Este
archivo es el prompt que el orquestador (`gestion-causas-orquestador`) despacha como
subagente en la Fase "smu" de cada corrida, siempre después de "calendario" y antes de
"goteo".

Objetivo de esta corrida: por cada correo nuevo de una demanda contra Rendic Hermanos,
Alvi, Super 10, Servicios Logísticos Santiago, Preunic o Salcobrand que llegue a
`nmunoz@gomezyriesco.cl`, registrar la causa (registro local siempre; Excel solo para las
4 primeras — ver paso 2i), crear su carpeta en Minutas, guardar la demanda adjunta, dejar
un borrador con los documentos de prueba a solicitar, y etiquetar la cadena con el color
de la empresa. **Nunca** envía correos ni borra nada (ni correos ni archivos), y no toca
el calendario.

**Regla de origen de la cadena** (acordada con el usuario): solo se procesan como causa
nueva las cadenas cuyo **primer mensaje** fue enviado por alguien de dominio `@smu.cl` o
`@sb.cl` — son los dos dominios desde los que las empresas mandantes derivan sus causas.
Las cadenas cuyo primer mensaje es de `@gomezyriesco.cl` son **internas** (Nico
discutiendo la causa con Román y el equipo) y **no se procesan aquí** — ver paso 2b. Esas
cadenas internas sí importan para el proyecto, pero las usa la tarea `gestion-causas-agenda`
(ahí es donde va el borrador con los montos demandados, respondiendo dentro de esa misma
cadena en vez de crear una nueva).

**Excepción (acordada con el usuario el 2026-08-17):** a veces la persona de la empresa
mandante le manda el cuadro-resumen **solo a Román** y no copia a Nico, así que lo primero
que aparece en la casilla de Nico es la respuesta de Román (dominio `@gomezyriesco.cl`)
con el cuadro-resumen de smu.cl/sb.cl citado adentro. Eso **no** es una cadena interna, es
el mismo tipo de intake normal — ver el detalle de cómo reconocerlo en el paso 2b.

Toda la parte mecánica se hace con el CLI `gestion_causas.cli` (paquete en
`Actualizador de informes\gestion_causas`), corrido con Bash/PowerShell desde
`Actualizador de informes` como directorio de trabajo:
`python -m gestion_causas.cli <subcomando> ...` — cada llamada imprime JSON a stdout.
Usa `python -m gestion_causas.cli --help` si necesitas recordar los argumentos exactos
de un subcomando.

## 0. Contexto de la corrida

El orquestador ya resolvió, antes de despacharte, lo que las 4 fases comparten. Leelo con
Read una sola vez, al empezar:
`Actualizador de informes\gestion_causas\_contexto_corrida.json`

De ahí sacás:
- `fecha_hoy` (AAAA-MM-DD), `dia_semana` y `es_lunes` — usá **esa** fecha en todo este
  archivo y no vuelvas a calcularla: si la corrida cruza la medianoche, dos fases podrían
  quedar con fechas distintas.
- `cache_calendario.ruta` — los eventos del calendario, traídos una sola vez para toda la
  corrida.
- `tokens` — el estado de los 3 tokens, ya verificado **sin** abrir ningún login
  interactivo. Si el orquestador te despachó, es porque los tokens de Gmail de trabajo y de
  Calendar están OK; no hace falta que los vuelvas a diagnosticar.

Si el archivo no existe (típicamente porque estás corriendo esta fase suelta a mano, fuera
del orquestador), seguí igual: calculá la fecha de hoy vos mismo y usá las llamadas en vivo
que se indican como fallback más abajo. Si en ese caso algún comando del CLI se queda
esperando un login interactivo, detente de inmediato, no reintentes, y deja como resumen
"La tarea no pudo autenticarse contra nmunoz@gomezyriesco.cl — falta autorizar el token de
forma interactiva."

El contexto ya verificó que el token está autorizado y atado a
`nmunoz@gomezyriesco.cl`, así que no hace falta que corras `diagnostico` de nuevo. Si aun
así un comando del CLI se queda esperando un login interactivo, detente de inmediato, no
reintentes, y deja como resumen final "La tarea no pudo autenticarse contra
nmunoz@gomezyriesco.cl — falta correr `python -m gestion_causas.cli diagnostico` una vez de
forma interactiva para autorizar el token." Nunca sigas operando sobre otra cuenta.

**Nota (2026-09-02):** el aviso sobre borradores de documentos sin enviar (que antes era
un paso 0b de esta fase) ahora lo hace el orquestador una sola vez por corrida, en su
paso 4, para armar la bandeja de acciones del panel — no hace falta que esta fase lo
repita.

## 1. Buscar correos candidatos

Ejecuta:
```
python -m gestion_causas.cli buscar-hilos --query "from:(smu.cl OR sb.cl OR gomezyriesco.cl) (subject:DEMANDA OR subject:\"PLAN DE SALIDA\" OR \"Fecha de ingreso al Pjud\") after:2026/07/01 -label:\"Procesado-GestionCausas\"" --max-resultados 50
```
Se incluye `gomezyriesco.cl` en la búsqueda a propósito, aunque esas cadenas no se
procesan (ver paso 2b) — es la única forma de que la etiqueta `Procesado-GestionCausas`
también las alcance y no las siga trayendo en cada corrida. El filtrado real de si una
cadena es válida (smu.cl/sb.cl) o interna (gomezyriesco.cl) se hace por hilo, no en esta
búsqueda.

**Nota (2026-09-25):** el filtro de asunto original (`subject:DEMANDA`) no detectó un
correo real de `dsanchezv@smu.cl` (causa M-23-2026, Soto/Rendic, JLT Yungay) cuyo asunto
no traía la palabra "DEMANDA" — solo `M-23-2026 JLT YUNGAY (SOTO/RENDIC) PLAN DE SALIDA
2026` — y por eso la búsqueda nunca lo trajo; se procesó a mano al notarlo. Se agregaron
dos ramas más al OR, sin sacar `subject:DEMANDA` (Salcobrand, Preunic y las demás
empresas casi siempre sí usan esa palabra en el asunto, así que se mantiene como ancla
principal):
- `subject:"PLAN DE SALIDA"` — nombre del programa de desvinculaciones de Rendic bajo el
  que llega buena parte de esta correspondencia; red de respaldo para asuntos Rendic que
  no calcen con el patrón "DEMANDA RIT ...".
- `"Fecha de ingreso al Pjud"` (sin `subject:`, así busca en todo el mensaje) — es una
  etiqueta fija de la plantilla del cuadro-resumen que SMU/sb.cl usa siempre,
  independiente de cómo redacten el asunto ese día; es la red más robusta de las tres
  porque ancla al contenido, no al asunto.

Ojo con la sintaxis exacta de Gmail: el OR debe repetir `subject:` en cada rama que sea
de asunto (`subject:DEMANDA OR subject:"PLAN DE SALIDA"`) — agrupar `subject:(A OR "B
C")` funciona pero mezclar ahí una rama sin `subject:` no aplica el filtro de asunto a
esa rama (queda como búsqueda de cualquier campo, que es lo que queremos para la frase
del cuadro-resumen). Si en el futuro un cambio no trae los resultados esperados, probá
primero sin la fecha/label para descartar que sea la sintaxis y no el contenido. Si
aparece un asunto o plantilla nueva que tampoco calce con ninguna rama, agregala acá en
vez de sacar el filtro por completo (sin él, la búsqueda por dominio trae demasiado
volumen de correspondencia no relacionada).

El `after:2026/07/01` es un límite acordado con el usuario: no procesar correspondencia
anterior a julio de 2026. Razón: causas de meses anteriores que ya se resolvieron y se
sacaron del Excel no se detectarían como duplicado (el chequeo de duplicado del paso 2i
solo mira lo que hoy está en el Excel), así que revisarlas podría crear una fila y una
carpeta nuevas para una causa que en realidad ya está cerrada. Para causas viejas que
siguen vivas, no hace falta ir a buscarlas: en algún momento llega correspondencia nueva
en esa cadena (dentro de la ventana de fecha) y ahí se revisa con el chequeo normal de
duplicado. No cambies esta fecha sin que el usuario lo pida.

Si `total` es 0, termina la corrida y entrega un resumen de "sin correos nuevos". El
volumen de correspondencia de julio-agosto es grande (puede rondar el límite de 50) — no
esperes vaciarlo en una sola corrida. El límite de 50 por corrida y la etiqueta de
control aseguran que cada corrida avance sin reprocesar lo ya visto; a las causas que ya
están registradas les basta con etiquetarlas y marcarlas procesadas (pasos 2e, 2l-2n),
sin recrear carpeta ni fila.

## 2. Por cada hilo encontrado

a. Trae todos los mensajes del hilo:
   ```
   python -m gestion_causas.cli leer-hilo --thread-id <id>
   ```
   Usa siempre el **primer mensaje del hilo** (el reenvío original con el cuadro
   resumen) para extraer los datos de la causa — los mensajes siguientes del mismo
   hilo suelen ser el CECO, documentos, o idas y vueltas.

b. **Determina el origen de la cadena.** Mira el campo `sender` del primer mensaje
   (paso 2a) y extrae el dominio (lo que sigue después de `@`):
   - Si es `smu.cl` o `sb.cl` → cadena válida, sigue con el paso 2c.
   - Si es `gomezyriesco.cl` → **antes de concluir que es interna**, revisa el cuerpo
     de ese primer mensaje: a veces la persona de la empresa mandante le escribe el
     cuadro-resumen **solo a Román** (sin copiar a Nico), y lo que Nico ve como
     "primer mensaje" del hilo es en realidad la respuesta de Román a esa persona
     (ej. "Estimada Daniela, acusamos recibo...") con el correo original y su cuadro
     resumen completo citado/anidado abajo (formato `> El ... escribió:` o similar).
     En ese caso la cadena **sí es válida** — trátala igual que si el primer mensaje
     fuera de smu.cl/sb.cl y sigue con el paso 2c, extrayendo el cuadro resumen del
     texto citado. La señal para reconocer este caso: el cuerpo del primer mensaje de
     Román es corto (acuse de recibo, "reclamaremos", etc.) y contiene, citado, un
     cuadro resumen completo (Rit, Tribunal, Demandante, etc.) firmado por alguien de
     dominio `@smu.cl` o `@sb.cl`.
     Si en cambio el primer mensaje de `gomezyriesco.cl` es Nico o Román **iniciando**
     una conversación (sin nada de smu.cl/sb.cl citado) — típicamente Nico
     preguntándole a Román sobre estrategia de una causa que ya está registrada
     (ofrecimientos, cómo contestar, etc.) — ahí sí es cadena **interna**. Marca el
     hilo como procesado (paso 2n) y sigue con el siguiente hilo, sin hacer nada más
     aquí — esta cadena la usa `gestion-causas-agenda`, no esta tarea.
   - Cualquier otro dominio → no es una demanda-notificación válida. Marca como
     procesado (paso 2n) y sigue con el siguiente, sin hacer nada más.

c. **Extrae el cuadro resumen** (Rit, Tribunal, Demandante, Rut, Fecha audiencia,
   Demandada, Cuantía, Conceptos demandados, Materia, Fecha de ingreso al Pjud, Hechos)
   aplicando exactamente las reglas de
   `Actualizador de informes\docs\2026-07-07-informe-juicios-email-design.md`
   (secciones "Mapeo de columnas" y "Plantilla del Resumen"). El asunto puede no
   coincidir con el RIT real del cuerpo — usa siempre el RIT del cuadro.

d. **Filtra por empresa.** La Demandada debe ser una de estas 6 (compara sin
   importar mayúsculas/tildes/razón social completa tipo "S.A."):
   - Rendic Hermanos
   - Alvi
   - Super 10
   - Servicios Logísticos Santiago
   - Preunic
   - Salcobrand

   Si la Demandada es otra empresa, marca el hilo como procesado (paso 2n) y sigue con
   el siguiente, sin hacer nada más. **Recuerda para el paso 2i:** Preunic y Salcobrand
   pasan por todas las fases igual que las otras 4, pero **nunca** se escriben en el
   Informe de Juicios Vigentes (ese Excel es solo del negocio de SMU).

e. **Verifica si ya está registrada:**
   ```
   python -m gestion_causas.cli causa-ya-registrada --rit "<rit>"
   ```
   Si `ya_registrada` es true, salta directo al paso 2l (etiquetar) y 2n (marcar
   procesado) — no dupliques carpeta, fila ni borrador de documentos. (El script del
   Excel igual detecta el duplicado, pero evitamos trabajo de más.)

f. **Busca el CECO.** Puede venir en el primer mensaje ("nos confirme el CECO
   [código]") o puede faltar. Si falta, revisa los demás mensajes del mismo hilo (ya
   los tienes de 2a) por si alguien ya lo contestó. Si de verdad no está en ningún
   mensaje, sigue igual — el CECO se completa en una corrida futura cuando llegue.

g. **Crea la carpeta de la causa** (apellido del demandante principal, sin el RUT):
   ```
   python -m gestion_causas.cli crear-carpeta --apellido "<apellido>" --empresa "<demandada>" --rit "<rit>"
   ```
   El comando primero busca si ya existe una carpeta en Minutas para este RIT (mira
   tanto el nombre de la carpeta como el nombre de los archivos que ya tiene adentro
   — causas que Nico ya armó a mano antes de esta automatización casi siempre traen el
   RIT en el nombre de la minuta o del "E-Acompaña documentos...", aunque la carpeta
   misma se llame solo "Apellido con Empresa") y la reusa en vez de crear una
   duplicada — revisa el campo `reusada` de la respuesta. **Ojo:** en el caso raro de
   que la carpeta vieja no tenga el RIT en ningún archivo (carpeta casi vacía, o
   documentos sin el RIT en el nombre), no la va a encontrar y va a crear una carpeta
   nueva al lado — si notas que el comando creó una carpeta que no esperabas para esa
   causa, detente, no sigas guardando documentos ahí, y anótalo en el resumen final
   para que Nico lo revise a mano.
   Usa la ruta devuelta (`carpeta`) para el paso siguiente.

h. **Guarda la demanda adjunta.** De los `adjuntos` del primer mensaje (paso 2a),
   identifica el PDF de la demanda (normalmente el único PDF grande adjunto al
   reenvío; ignora imágenes de firma, el CLI ya las filtra automáticamente) y
   guárdalo como `demanda.pdf`:
   ```
   python -m gestion_causas.cli guardar-adjunto --message-id <id-del-mensaje> --attachment-id <id> --carpeta "<carpeta>" --nombre-archivo demanda.pdf
   ```
   Si `guardado` es false porque "parece firma/logo" y en realidad sí era la demanda
   (raro, pero puede pasar con adjuntos chicos), repite el comando agregando
   `--forzar`. Si no hay ningún adjunto que parezca la demanda, sigue sin ella —
   anótalo en el resumen final para que Nico la suba a mano.

i. **Escribe la fila en el Informe de Juicios Vigentes — solo si la Demandada es
   Rendic Hermanos, Alvi, Super 10 o Servicios Logísticos Santiago.** Si es Preunic o
   Salcobrand, **sáltate este paso por completo** (no ejecutes el script) y sigue
   directo al 2j; anota en el resumen final que esa causa no aplica a Excel.

   Para las 4 empresas de SMU: arma el JSON con
   `{"juzgado", "materia", "causa", "cuantia", "resumen"}` (mismas reglas de la
   Plantilla del Resumen), guárdalo en un archivo temporal, y corre:
   ```
   python "..\actualizar_informe_juicios.py" --json-file "<ruta_al_json>"
   ```
   (ruta relativa desde `gestion_causas`, o usa la ruta absoluta de
   `Actualizador de informes\actualizar_informe_juicios.py`). Código de salida 0 o 3
   (duplicado) → continúa. Código 1 (Excel abierto/bloqueado, o datos incompletos) →
   **no marques el hilo como procesado**, anota el error en el resumen final, y sigue
   con el siguiente hilo.

j. **Registra la causa** en el estado local (para reuso del EERR y para
   `causa-ya-registrada` de corridas futuras). Incluye `fecha_audiencia` si el cuadro la
   trae (la usa la Fase 4 más abajo) en formato AAAA-MM-DD — si dice "Pendiente
   reclamación" o algo no-fecha, omite el campo. Incluye también `"aplica_excel": false`
   si la empresa es Preunic o Salcobrand (o `true` para las otras 4, por claridad):
   ```
   python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con empresa, ceco (si hay), demandante, carpeta, fecha_despido, fecha_audiencia (si hay), thread_id, tiene_demanda, aplica_excel>"
   ```

k. **Redacta el borrador de documentos a solicitar (Fase 2)** — solo si guardaste la
   demanda en el paso 2h (sin demanda no hay de dónde sacar qué se demanda además del
   cuadro; si no hay demanda, sáltate este paso y anótalo en el resumen final). Aplica
   igual para las 6 empresas, incluidas Preunic y Salcobrand.

   1. Lee el PDF de la demanda que acabas de guardar para entender qué se demanda,
      más allá de lo que ya viene resumido en "Conceptos demandados" del cuadro. El
      objetivo es **solo** detectar los ajustes del punto 4 más abajo (base de cálculo,
      descuentos indebidos, horas extra, etc.) — no resumir la demanda completa.
      **Acota la lectura:** andá directo a la sección de "Hechos"/"Antecedentes"
      (normalmente las primeras páginas, después de la identificación de las partes) y a
      la sección final de "Petitorio"/"Por tanto" (donde están los conceptos y montos
      exactos) — saltate el cuerpo intermedio de fundamentos de derecho (citas de ley,
      doctrina, jurisprudencia), que no aporta nada nuevo frente al cuadro-resumen. Si el
      PDF tiene capa de texto normal, esto es barato y no hace falta cuidarlo más. **Si el
      PDF es un escaneo** (sin capa de texto, se lee en modo visión página por página): no
      leas más de ~10-12 páginas salvo que el documento sea evidentemente más largo y el
      petitorio esté más adelante — en ese caso, leé igual las páginas de Hechos y después
      andá directo a las últimas 2-3 páginas (ahí casi siempre está el Petitorio), sin
      recorrer visualmente todo el medio.
   2. Parte de esta lista base, en este orden exacto:
      ```
      1. Contrato de trabajo y anexos
      2. Carta de despido
      3. Finiquito
      4. EERR del local de los años 2024, 2025 y 2026
      5. Comparativa de dotación del local antes y después del despido
      6. Testigos
      7. Absolvente
      ```
   3. **Reuso del EERR**: si tienes CECO y fecha de despido, corre
      ```
      python -m gestion_causas.cli buscar-eerr-reusable --ceco "<ceco>" --fecha-despido "<AAAA-MM-DD>"
      ```
      Si `reusable` no es null: **quita el punto 4** de la lista, y copia el EERR de la
      causa anterior a esta carpeta (busca su carpeta y el nombre del archivo con
      `python -m gestion_causas.cli obtener-causa --rit "<reusable.rit_causa>"`, mira su
      campo `carpeta`, y lista sus archivos con `listar-carpeta` para identificar cuál
      parece el EERR):
      ```
      python -m gestion_causas.cli copiar-archivo --origen "<carpeta de esa causa>\<archivo EERR>" --carpeta-destino "<carpeta de esta causa>" --nombre-archivo "<mismo nombre>"
      ```
      Anota en el resumen final "EERR reusado del CECO X (causa <rit_causa>)".
   4. **Ajustes según lo demandado** (compara contra "Conceptos demandados" del cuadro
      y lo que leíste en la demanda):
      - Si se demanda **diferencia en la base de cálculo** de la indemnización por
        años de servicio o de la sustitutiva de aviso previo: agrega
        *"Últimas 6 liquidaciones de remuneraciones"* como punto nuevo, **antes** de
        Testigos y Absolvente.
      - Si se demanda cualquier otra cosa además de lo típico (ej. un descuento
        indebido en el finiquito por un préstamo, una diferencia por horas
        extraordinarias, etc.): agrega, en el mismo estilo escueto (solo el nombre del
        documento, sin explicar por qué), el antecedente que permita desvirtuarlo o
        estudiar su procedencia — ej. "Antecedentes de la procedencia del préstamo" —
        también antes de Testigos y Absolvente.
   5. Redacta el borrador **como respuesta dentro de la misma cadena**, dirigido a
      quien corresponda en el hilo (normalmente la persona de SMU/sb.cl que envió la
      demanda, o quien aparezca en copia pidiendo que le ayuden con los antecedentes —
      usa el criterio del hilo). El cuerpo del borrador es **únicamente la lista
      numerada de documentos**, sin saludo, sin explicación, sin firma — nada más que
      la lista. Escribe el cuerpo a un archivo temporal, una línea por documento (con o
      sin numeración manual, da igual), y crea el borrador con `--lista` para que Gmail
      la reciba como lista numerada nativa (`<ol>`) — así Nico puede insertar o quitar
      un documento en el medio sin tener que renumerar el resto a mano:
      ```
      python -m gestion_causas.cli crear-borrador --destinatario "<correo>" --asunto "Re: <asunto original>" --cuerpo-archivo "<ruta.txt>" --thread-id <id> --lista
      ```
      El comando ya evita duplicar el borrador si la cadena ya tiene uno — no te
      preocupes por eso, pero revisa `creado` en la respuesta para el resumen final.
      Si `creado` es true, guarda el `draft_id` devuelto **junto con la lista de
      documentos pedidos** (uno por línea, sin numeración) en el registro de la causa —
      el `draft_id` es para que `verificar-borradores-pendientes` (que ahora corre el
      orquestador, paso 4) pueda avisar si Nico todavía no lo envió; la lista es para
      que, cuando el subagente "seguimiento" note que Nico lo envió, sepa qué se pidió
      sin tener que releer el correo:
      ```
      python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con {\"borrador_documentos_draft_id\": \"<draft_id>\", \"documentos_solicitados\": [\"Contrato de trabajo\", \"Carta de despido\", ...]}>"
      ```

l. **Etiqueta el hilo con el color de la empresa:**
   ```
   python -m gestion_causas.cli etiquetar-empresa --thread-id <id> --empresa "<una de las 6 exactas: Rendic Hermanos | Alvi | Super 10 | Servicios Logísticos Santiago | Preunic | Salcobrand>"
   ```
   Las etiquetas "Preunic" y "Salcobrand" ya existían en la casilla antes de esta
   automatización — el comando las reusa tal cual (con su color actual), no las
   recrea.

m. **Anota en la bitácora** cada acción relevante que tomaste para esta causa (fila
   agregada/duplicada/no-aplica-Excel, carpeta creada, demanda guardada o faltante,
   CECO pendiente, borrador de documentos creado o no):
   ```
   python -m gestion_causas.cli bitacora --rit "<rit>" --mensaje "<qué se hizo>"
   ```

n. **Marca el hilo como procesado** — solo si no hubo error de Excel bloqueado en 2i:
   ```
   python -m gestion_causas.cli marcar-procesado --thread-id <id>
   ```

## 3. Resumen final

Tu **último mensaje** de esta ejecución debe ser **un único objeto JSON**, sin texto antes
ni después y sin envolverlo en \`\`\` — el orquestador lo copia tal cual a la sección "Fase
smu" del panel de estado. Formato:

```json
{
  "fase": "smu",
  "titular": "<una frase: ej. \"2 causas nuevas registradas, 2 borradores de documentos creados\">",
  "metricas": [
    {"etiqueta": "Causas nuevas", "valor": N},
    {"etiqueta": "Borradores de documentos creados", "valor": N},
    {"etiqueta": "EERR reusado", "valor": N},
    {"etiqueta": "Cadenas internas encontradas", "valor": N},
    {"etiqueta": "Otra empresa (ignorados)", "valor": N},
    {"etiqueta": "RIT duplicado", "valor": N},
    {"etiqueta": "Pendientes por error de Excel", "valor": N}
  ],
  "items": [
    {"rit": "<rit>", "titulo": "<empresa> - <demandante>",
     "detalle": "<demanda guardada o falta; CECO guardado o falta; aplica o no al Excel; EERR reusado del RIT X si corresponde>"}
  ],
  "acciones": [],
  "notas": []
}
```

- `items`: una entrada por cada causa **nueva** registrada en esta corrida (no repitas las
  que ya estaban y solo se etiquetaron/marcaron de nuevo).
- `acciones`: solo si algo requiere que Nico decida algo **ahora** (ej. un hilo con RIT
  ambiguo que no pudiste resolver solo, o un patrón de asunto nuevo que no calza con nada
  conocido) — formato `{"rit": "<rit o null>", "que": "<qué necesita revisar>", "urgencia":
  "alta"|"media"|"baja"}`. Las causas pendientes por Excel bloqueado **no** van acá — se
  reintentan solas en la próxima corrida, no requieren que Nico haga nada.
- `notas`: observaciones de criterio que quieras dejarle a Nico sin que sean urgentes (ej.
  un dominio nuevo visto en un remitente).
- Si hubo el problema de autenticación del paso 0, tu resumen es en cambio
  `{"fase": "smu", "error": "La tarea no pudo autenticarse contra nmunoz@gomezyriesco.cl — falta autorizar el token de forma interactiva."}`
  y no sigas con el resto.

No hace falta ser extenso si no hubo novedades.