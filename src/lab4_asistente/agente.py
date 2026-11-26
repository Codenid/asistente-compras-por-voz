# ===== Agente: bucle LLM + herramientas =====
"""Agente de compras: un solo LLM que elige herramientas en un bucle por turno.

Control implementado por el grupo:
- Memoria: Estado (presupuesto, preferencias, carrito, cotizacion, pedidos, productos mostrados) inyectado en
  cada turno + historial recortado.
- Bucle: el LLM propone llamadas a herramientas; el codigo las valida y ejecuta; termina cuando responde texto.
- Reglas duras por codigo (no dependen del LLM): consentimiento explicito, validacion de cantidades,
  presupuesto y existencias, confirmacion atomica e idempotente.
"""
import json
import re
import time

from .herramientas import ESQUEMAS, MODIFICAN_CARRITO, es_confirmacion
from .recuperacion import normalizar


SISTEMA = """Eres un asistente de compras por voz de una tienda en linea. Hablas en espanol y respondes breve \
(maximo 3 frases), porque tu respuesta se leera en voz alta.
Reglas:
1. Usa SIEMPRE las herramientas para obtener productos, precios, existencias y atributos. No inventes datos.
2. Si un atributo no figura en la informacion del producto, dilo como desconocido (usa consultar_atributo).
3. Si falta informacion para actuar (que producto, para que dispositivo, talla, cantidad) o hay una ambiguedad \
relevante, haz UNA pregunta de aclaracion antes de tocar el carrito.
4. Cuando el usuario mencione presupuesto o preferencias, guardalos con registrar_restricciones y respetalos al \
buscar y al elegir.
5. Para comprar: agrega al carrito, usa cotizar, presenta el total y pide confirmacion explicita. Llama a \
confirmar_pedido solo si el ultimo mensaje del usuario confirma la cotizacion ya presentada.
6. Si un producto esta agotado o no alcanza el stock, propone una alternativa disponible o explica que no hay solucion.
7. Si confirmar_pedido informa problemas (stock o precio cambiados), explicalo, propone una solucion y vuelve a \
cotizar. Si el pedido ya existe, no lo repitas.
8. Si el usuario cambia una cantidad o preferencia, conserva las demas restricciones.
9. Nombra los productos por su nombre corto y precio; no leas identificadores. Importes en euros con dos decimales."""

SISTEMA += """
10. En buscar_productos incluye siempre la cantidad solicitada.
Recuperala del mensaje y del historial; no confundas cantidad de productos con
capacidades, tamaños o modelos. Registra el presupuesto antes de buscar.
Para una consulta informativa sin intencion de compra puedes buscar una unidad;
esto no autoriza agregarla al carrito.
11. Para "la primera" usa la posicion de los resultados que presentaste.
Para "la mas barata", compara los precios de esos resultados.
12. Agregar requiere agregar_al_carrito; modificar o quitar requiere
cambiar_cantidad; preparar un total de compra requiere cotizar.
Nunca describas estas acciones como realizadas sin resultados exitosos.
13. Conserva la cantidad solicitada: "agrega la primera" no significa
agregar una sola unidad si antes se pidieron tres.
14. Si el usuario sustituye un producto, elimina el anterior con
cambiar_cantidad(..., cantidad=0), busca el reemplazo y cotiza nuevamente.
No hagas una sustitucion que el usuario no autorizo.
15. Si una herramienta devuelve ok=False, explica el error o corrigelo
usando las herramientas. No afirmes que la operacion se completo.
"""

ID_RE = re.compile(r"\bB0[0-9A-Z]{8}\b")


def limpiar_respuesta(t):
    """Texto apto para TTS: sin markdown ni identificadores."""
    t = re.sub(r"[*#`_]+", "", t or "")
    t = ID_RE.sub("", t)
    t = re.sub(r"\(\s*\)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def es_aclaracion(t):
    return "?" in t


def accion_sin_respaldo(texto, operaciones):
    """Detector heuristico: no garantiza cubrir todas las formulaciones."""
    texto = normalizar(texto)
    exitosas = {
        op["herramienta"] for op in operaciones if op["resultado"].get("ok")
    }
    reglas = [
        (r"\b(?:agregue|anadi|se agrego|se agregaron|he agregado|he anadido)\b",
         {"agregar_al_carrito"}),
        (r"\b(?:actualice|modifique|cambie|quite|elimine|se actualizaron|"
         r"se actualizo|se modifico|se elimino)\b", {"cambiar_cantidad"}),
    ]
    for patron, herramientas in reglas:
        if re.search(patron, texto) and not exitosas.intersection(herramientas):
            return ", ".join(sorted(herramientas))
    afirma_cotizacion = re.search(
        r"\b(?:esta cotizacion|cotizacion lista|he preparado la cotizacion)\b", texto
    )
    cotizacion_valida = any(
        op["herramienta"] == "cotizar" and op["resultado"].get("ok")
        and op["resultado"].get("valida") for op in operaciones
    )
    if afirma_cotizacion and not cotizacion_valida:
        return "cotizar"
    return None


class Agente:
    def __init__(self, llm, herramientas, max_pasos=8, turnos_historial=6):
        self.llm, self.h = llm, herramientas
        self.max_pasos, self.turnos = max_pasos, turnos_historial

    @property
    def estado(self):
        return self.h.estado

    def turno(self, texto):
        e = self.estado
        e.texto_usuario = texto
        e.cotizo_en_turno = False
        self.h.t_recuperacion = 0.0
        msgs = [{"role": "system", "content": SISTEMA + "\n\n" + self.h.resumen_estado()}]
        for u, a in e.historial[-self.turnos:]:
            msgs += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
        msgs.append({"role": "user", "content": texto})
        ops, t_llm, t_tools, respuesta, crudo = [], 0.0, 0.0, None, []

        # En el punto crítico, el código ejecuta la confirmación explícita sobre
        # la cotización vigente; la respuesta no depende de que el LLM recuerde llamar la herramienta.
        if e.cotizacion and e.cotizacion_mostrada and es_confirmacion(texto):
            t0 = time.perf_counter()
            res = self.h.ejecutar("confirmar_pedido", {})
            t_tools += time.perf_counter() - t0
            ops.append({"paso": 0, "herramienta": "confirmar_pedido", "argumentos": {}, "resultado": res})
            if res.get("ok"):
                respuesta = (f"Pedido registrado por {res['total']:.2f} euros."
                             if res.get("estado") == "registrado" else
                             f"Ese pedido ya estaba registrado por {res['total']:.2f} euros; no lo dupliqué.")
            else:
                respuesta = "No registré el pedido porque cambiaron las condiciones de la cotización. " \
                            "Puedo buscar una alternativa y preparar una nueva cotización."
            e.historial.append((texto, respuesta))
            return {"entrada": texto, "respuesta": respuesta, "operaciones": ops, "pasos_llm": 0,
                    "aclaracion": False, "t_llm": 0.0, "t_herramientas": t_tools,
                    "t_recuperacion": 0.0, "crudo": []}

        for paso in range(1, self.max_pasos + 1):
            t0 = time.perf_counter()
            out = self.llm.generar(msgs, ESQUEMAS)
            t_llm += time.perf_counter() - t0
            crudo.append(out.get("crudo", ""))
            llamadas = out.get("llamadas", [])
            if not isinstance(llamadas, list):
                respuesta = "No pude interpretar la respuesta del asistente. Inténtalo de nuevo."
                break

            nombres_validos = {s["function"]["name"] for s in ESQUEMAS}
            invalidas = [
                llamada for llamada in llamadas
                if not isinstance(llamada, dict)
                or llamada.get("nombre") not in nombres_validos
                or not isinstance(llamada.get("argumentos"), dict)
            ]
            if invalidas:
                # No ejecutar llamadas malformadas ni tratarlas como respuesta natural.
                resumen_error = ", ".join(
                    str(llamada.get("nombre", "llamada inválida"))
                    if isinstance(llamada, dict) else "llamada inválida"
                    for llamada in invalidas
                )
                ops.append({
                    "paso": paso,
                    "herramienta": "_llamada_invalida",
                    "argumentos": {},
                    "resultado": {"ok": False, "error": resumen_error},
                })
                respuesta = (
                    "No pude interpretar una acción solicitada. "
                    "No se modificó el carrito ni se registró ningún pedido."
                )
                break

            if not llamadas:
                candidata = limpiar_respuesta(out.get("texto", ""))
                pendiente = accion_sin_respaldo(candidata, ops)
                if pendiente:
                    msgs.append({"role": "assistant", "content": candidata})
                    msgs.append({
                        "role": "system",
                        "content": (
                            "La respuesta anterior afirma una accion sin respaldo "
                            "en las operaciones de este turno. "
                            f"Herramienta pendiente: {pendiente}. "
                            "Ejecuta la herramienta con argumentos validos si el "
                            "usuario autorizo la accion. Si falta informacion, "
                            "pide aclaracion. No repitas una afirmacion de exito "
                            "sin evidencia.\n" + self.h.resumen_estado()
                        ),
                    })
                    continue
                respuesta = candidata
                break
            msgs.append({"role": "assistant", "content": out.get("texto", ""),
                         "tool_calls": [{"type": "function", "function": {"name": c["nombre"],
                                                                          "arguments": c["argumentos"]}}
                                        for c in llamadas]})
            for c in llamadas:
                t1 = time.perf_counter()
                res = self.h.ejecutar(c["nombre"], c["argumentos"])
                t_tools += time.perf_counter() - t1
                ops.append({"paso": paso, "herramienta": c["nombre"], "argumentos": c["argumentos"], "resultado": res})
                msgs.append({"role": "tool", "name": c["nombre"], "content": json.dumps(res, ensure_ascii=False)})
        if not respuesta:
            respuesta = "Disculpa, no pude completar la solicitud. ¿Puedes repetirla con mas detalle?"
        confirmacion_exitosa = any(
            o["herramienta"] == "confirmar_pedido" and o["resultado"].get("ok")
            for o in ops
        )
        afirma_pedido = re.search(r"pedido.{0,35}(confirmad|registrad)|(?:confirmad|registrad).{0,35}pedido",
                                  normalizar(respuesta))
        if afirma_pedido and not confirmacion_exitosa:
            respuesta = "Aún no registré el pedido. Primero debo mostrarte una cotización válida y recibir tu confirmación."
        if e.cotizo_en_turno:           # la cotizacion queda "mostrada" recien al entregar esta respuesta
            e.cotizacion_mostrada = True
        e.historial.append((texto, respuesta))
        return {"entrada": texto, "respuesta": respuesta, "operaciones": ops, "pasos_llm": len(crudo),
                "aclaracion": es_aclaracion(respuesta) and not any(
                    o["herramienta"] in MODIFICAN_CARRITO and o["resultado"].get("ok") for o in ops),
                "t_llm": t_llm, "t_herramientas": t_tools - self.h.t_recuperacion,
                "t_recuperacion": self.h.t_recuperacion, "crudo": crudo}
