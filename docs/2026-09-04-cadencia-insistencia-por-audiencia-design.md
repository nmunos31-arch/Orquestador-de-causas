# Cadencia de insistencia sin tope, atada a la fecha de audiencia

## Contexto

`registro.puede_insistir()` (ver [2026-08-19-seguimiento-sin-respuesta-design.md](2026-08-19-seguimiento-sin-respuesta-design.md))
aplica hoy la cadencia acordada en su momento: el 1er aviso siempre procede; el 2º
solo si pasaron ≥2 días hábiles desde el 1º; **del 3er aviso en adelante, nunca** —
el hilo queda para siempre como "requiere gestión manual" en el resumen de las
tareas programadas (`gestion-causas-sin-respuesta`, `gestion-causas-documentos-
pendientes`).

En la práctica esto corta la insistencia demasiado pronto cuando a la causa
todavía le queda mucho tiempo antes de la audiencia: dos avisos y silencio no
significa que haya que dejar de insistir, sino que hay que insistir con una
cadencia más laxa (si falta tiempo) o más agresiva (si la audiencia está
cerca). El usuario pidió que, en vez de "nunca", la cadencia después del 2º
aviso dependa de cuánto falta para la `fecha_audiencia` de la causa asociada al
hilo:

- Si faltan **más de 2 semanas**: repetir el mismo patrón de siempre en bucle —
  4 días hábiles, luego 2 días hábiles, luego 4, luego 2...
- Si faltan **menos de 2 semanas**: insistir cada 2 días hábiles.
- Si falta **menos de 1 semana**: insistir a diario (cada día hábil).

El tier se recalcula en cada llamada (no se fija una vez al agotar el 2º
aviso) — si una causa que empezó con la audiencia lejana la va teniendo más
cerca con el paso de los avisos, el próximo aviso simplemente usa el umbral
del tier vigente en ese momento, sin intentar "terminar" el ciclo 4/2 a medias.

Si el hilo no tiene RIT asociado en `registro_seguimiento.json`, o la causa de
ese RIT no tiene `fecha_audiencia` registrada, no hay cómo elegir tier: se
reporta explícitamente que la causa no está agendada, en vez de mezclarlo con
el motivo genérico de "faltan días".

## Decisión tomada con el usuario

- Recalcular el tier en cada llamada a `puede_insistir`, según la fecha de hoy.
- Ciclo 4/2 días hábiles en bucle indefinido mientras el tier sea "lejano".
- Los tres umbrales de cadencia (4, 2, diario) son **días hábiles**, igual que
  ya usa el 1er/2º aviso.
- El umbral de tier (2 semanas / 1 semana) se mide en **días corridos** de
  calendario desde hoy hasta `fecha_audiencia`.
- Sin RIT o sin `fecha_audiencia`: `puede: False` con motivo distintivo ("causa
  no tiene audiencia agendada"), no el genérico de "ya se hicieron N avisos".

## Diseño

Un solo cambio de lógica, sin componentes nuevos.

### `gestion_causas/registro.py` — `puede_insistir`

Nueva firma:

```python
def puede_insistir(
    thread_id: str,
    hoy=None,
    ruta: Path = RUTA_REGISTRO_SEGUIMIENTO,
    ruta_feriados=None,
    ruta_causas: Path = RUTA_REGISTRO_CAUSAS,
) -> dict:
```

(mismo patrón de `ruta_causas` inyectable que ya usa `pedidos_abiertos`).

El 1er y 2º aviso no cambian. La rama de `len(avisos) >= 2` deja de devolver
siempre `puede: False` "requiere gestión manual" y pasa a:

1. `rit = entrada.get("rit")`. Si no hay rit, o `obtener_causa(rit, ruta_causas)`
   es `None`, o esa causa no tiene `fecha_audiencia`:
   ```python
   {"puede": False, "n_aviso": len(avisos) + 1,
    "motivo": "causa no tiene audiencia agendada, requiere revision manual"}
   ```
2. Si hay fecha: `dias_hasta_audiencia = (fecha_audiencia - hoy).days` (puede
   ser negativo si la audiencia ya pasó; no es un caso especial, cae en el
   tier "cercano" igual que faltando pocos días — insistir a diario sigue
   siendo lo razonable con audiencia encima o vencida).
3. Umbral de días hábiles exigidos desde el último aviso, según tier:
   - `dias_hasta_audiencia > 14` → **lejano**: alterna 4 y 2 según la paridad
     de `len(avisos) - 2` (0 → 4, 1 → 2, 2 → 4, 3 → 2, ...). Es decir, el 3er
     aviso pide 4 días hábiles desde el 2º, el 4º pide 2 días hábiles desde el
     3º, el 5º vuelve a pedir 4, etc.
   - `8 <= dias_hasta_audiencia <= 14` → **medio**: siempre 2.
   - `dias_hasta_audiencia <= 7` → **cercano**: siempre 1.
4. `transcurridos = dias_habiles_entre(avisos[-1]["fecha"], hoy, ...)`. Si
   `transcurridos >= umbral`: `puede: True`, motivo indica tier y umbral
   (ej. `"pasaron 4 dias habiles (tier lejano, ciclo 4/2, corresponde 4)"`).
   Si no: `puede: False`, motivo con lo que falta (ej. `"solo pasaron 1 dias
   habiles, tier medio exige 2"`).

`n_aviso` sigue siendo `len(avisos) + 1` siempre — ya no hay un tope que lo
convierta en "el que se agotó".

### `gestion_causas/cli.py`

Actualizar el `help=` del subparser `puede-insistir` (línea ~1056), que hoy
dice "1er aviso siempre, 2do a los 2 dias habiles, despues nunca" — ya no es
cierto. Nuevo texto: algo como "1er aviso siempre, 2do a los 2 dias habiles,
despues segun cercania a la audiencia (4/2 dias en bucle si faltan +2
semanas, cada 2 dias si faltan -2 semanas, diario si falta -1 semana)".

Sin flags nuevos: `ruta_causas` usa su default (`RUTA_REGISTRO_CAUSAS`), igual
que `ruta`/`ruta_feriados` ya no son flags de CLI hoy.

### `gestion_causas/subagentes/seguimiento.md`

Actualizar la mención de `puede-insistir` (~línea 164) para que la IA sepa que
ya no hay un tope duro: un hilo puede seguir recibiendo borradores de
insistencia indefinidamente mientras la causa siga sin resolverse, con
cadencia creciente a medida que se acerca la audiencia. Aclarar que un
`puede: false` con motivo "no tiene audiencia agendada" se debe reportar en el
resumen como un caso aparte (causa sin fecha de audiencia, no un simple "aún
no toca insistir").

## Manejo de errores

No se agrega validación nueva. `obtener_causa` y el parseo de `fecha_audiencia`
ya existen y ya se usan en otras partes del módulo (`causas_para_goteo`) con el
mismo criterio de fallar tal cual si el dato viene corrupto — no es un caso
visto en producción y no se justifica blindarlo aquí.

## Testing

En `tests/test_registro.py`, junto a los tests existentes de `puede_insistir`
(que cubren 1er/2º aviso):

- Sin rit en la entrada → motivo "no tiene audiencia agendada".
- Con rit pero la causa no tiene `fecha_audiencia` → mismo motivo.
- Tier lejano (`fecha_audiencia` a >14 días corridos de `hoy`): 3er aviso exige
  4 días hábiles desde el 2º (`puede: False` antes, `puede: True` después);
  4º aviso exige 2 días hábiles desde el 3º; 5º vuelve a exigir 4 (confirma el
  bucle, no solo una alternancia de dos pasos).
- Tier medio (8-14 días corridos): cualquier aviso posterior al 2º exige 2
  días hábiles desde el anterior.
- Tier cercano (≤7 días corridos, incluida fecha ya pasada): exige 1 día
  hábil desde el anterior.

```bash
python -m pytest tests/test_registro.py -q
```

## Archivos

| Archivo | Cambio |
|---|---|
| `gestion_causas/registro.py` | `puede_insistir`: nuevo param `ruta_causas`, cadencia sin tope por tier de audiencia |
| `gestion_causas/cli.py` | actualizar `help=` del subparser `puede-insistir` |
| `gestion_causas/subagentes/seguimiento.md` | actualizar mención de la cadencia sin tope |
| `tests/test_registro.py` | casos nuevos por tier y por causa sin audiencia agendada |
| `docs/2026-09-04-cadencia-insistencia-por-audiencia-design.md` | **nuevo** — este diseño |
