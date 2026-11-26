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
from .recuperacion import normalizar, tokens


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
16. Una orden explicita como "agrega", "pon", "quita" o "cotiza" ya es
autorizacion para ejecutar esa accion. No vuelvas a pedir permiso para tocar el
carrito. La confirmacion adicional se exige solo para registrar el pedido.
17. Si el usuario responde a una aclaracion pendiente con cantidad y producto,
continua la accion original. No abras una segunda aclaracion sobre atributos
opcionales. Si cambia color, marca u otra preferencia, busca de nuevo y no uses
la lista anterior.
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


def cantidad_mencionada(texto, predeterminada=1):
    """Extrae cantidades pequeñas para el fallback de búsqueda, no para comprar."""
    t = normalizar(texto)
    numero = re.search(r"\b([1-9]|10)\b", t)
    if numero:
        return int(numero.group(1))
    palabras = {
        "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3,
        "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
        "ocho": 8, "nueve": 9, "diez": 10,
    }
    for palabra, cantidad in palabras.items():
        if re.search(rf"\b{palabra}\b", t):
            return cantidad
    return predeterminada


def accion_sin_respaldo(texto, operaciones):
    """Detector heuristico: no garantiza cubrir todas las formulaciones."""
    texto = normalizar(texto)
    exitosas = {
        op["herramienta"] for op in operaciones if op["resultado"].get("ok")
    }
    reglas = [
        (r"\b(?:agregue|agregamos|agregado|anadi|se agrego|se agregaron|"
         r"se han agregado|he agregado|he anadido)\b",
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


def accion_solicitada_pendiente(texto, historial, operaciones):
    """Detecta órdenes explícitas que el LLM intentó posponer o solo describir."""
    actual = normalizar(texto)
    if re.search(r"\b(?:no|nunca)\b.{0,20}\b(?:agreg|anad|pon|compr)", actual):
        return None
    exitosas = {
        op["herramienta"] for op in operaciones if op["resultado"].get("ok")
    }
    requeridas = []
    if re.search(r"\b(?:agrega|agregue|anade|pon|coloca)\b", actual):
        requeridas.append("agregar_al_carrito")
    if re.search(r"\b(?:quita|elimina|retira|cambia la cantidad)\b", actual):
        requeridas.append("cambiar_cantidad")
    if re.search(r"\b(?:cotiza|cotizacion|dime el total|dame el total)\b", actual):
        requeridas.append("cotizar")
    if re.search(r"\b(?:quiero|necesito|busca|buscar|comprar)\b", actual):
        requeridas.append("buscar_productos")
    cambia_preferencia = re.search(
        r"\b(?:mejor que sea|cambia|cambiala|color|marca)\b", actual
    )
    if cambia_preferencia:
        requeridas.append("buscar_productos")
    # Una respuesta concreta completa la solicitud de agregar que quedó
    # pendiente por falta de cantidad/modelo en turnos anteriores.
    if not requeridas and historial and any(
        re.search(r"\b(?:agrega|anade|pon)\b", normalizar(u))
        for u, _ in historial[-2:]
    ):
        requeridas.append("agregar_al_carrito")
    pendientes = [nombre for nombre in requeridas if nombre not in exitosas]
    return ", ".join(dict.fromkeys(pendientes)) or None


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
                # Si cambió el precio, el carrito sigue siendo válido y se
                # puede presentar inmediatamente una nueva cotización. El
                # usuario deberá confirmarla en un turno posterior.
                nueva = self.h.ejecutar("cotizar", {})
                ops.append({"paso": 0, "herramienta": "cotizar", "argumentos": {}, "resultado": nueva})
                if nueva.get("ok") and nueva.get("valida"):
                    e.cotizacion_mostrada = True
                    respuesta = (
                        "No registré el pedido porque cambió el precio. "
                        f"La nueva cotización es de {nueva['total']:.2f} euros. "
                        "Confirma si aceptas el nuevo total."
                    )
                else:
                    respuesta = "No registré el pedido porque cambiaron las condiciones de la cotización. " \
                                "Puedo buscar una alternativa y preparar una nueva cotización."
            e.historial.append((texto, respuesta))
            return {"entrada": texto, "respuesta": respuesta, "operaciones": ops, "pasos_llm": 0,
                    "aclaracion": False, "t_llm": 0.0, "t_herramientas": t_tools,
                    "t_recuperacion": 0.0, "crudo": []}

        # Un cambio explícito de color debe reemplazar la lista mostrada. Se
        # reconstruye la consulta con el producto del turno anterior, quitando
        # colores viejos, y se deja al LLM presentar las nuevas opciones.
        actual_norm = normalizar(texto)
        if e.mostrados and re.search(r"\b(?:color|mejor que sea)\b", actual_norm):
            colores = {
                token
                for valor in self.h.cat["color"].dropna().astype(str).unique()
                for token in normalizar(valor).split()
                if len(token) >= 3
            }
            previo = e.historial[-1][0] if e.historial else ""
            base = " ".join(t for t in normalizar(previo).split() if t not in colores)
            cantidad = e.mostrados[0].get("cantidad_solicitada", 1)
            args = {"consulta": f"{base} {texto}".strip(), "cantidad": cantidad}
            if e.presupuesto_cent is not None:
                args["precio_max"] = e.presupuesto_cent / 100
            t0 = time.perf_counter()
            res = self.h.ejecutar("buscar_productos", args)
            t_tools += time.perf_counter() - t0
            ops.append({"paso": 0, "herramienta": "buscar_productos", "argumentos": args, "resultado": res})
            msgs.append({
                "role": "system",
                "content": "Se actualizó la búsqueda por el cambio de preferencia: "
                           + json.dumps(res, ensure_ascii=False),
            })

        # Resuelve referencias posicionales o al carrito con IDs reales del
        # estado. Estas acciones son explícitas y reversibles; confirmar el
        # pedido sigue requiriendo una cotización mostrada y otro turno.
        if re.search(r"\b(?:quita|elimina|retira)\b", actual_norm):
            carrito = self.h.ver_carrito()["carrito"]
            items = carrito.get("items", [])
            objetivo = set(tokens(texto)) - {
                "quita", "elimina", "retira", "carrito", "del", "la", "el"
            }
            candidatos = [
                item for item in items
                if objetivo.intersection(tokens(item.get("titulo", "")))
            ]
            if len(candidatos) == 1 or (not candidatos and len(items) == 1):
                item = candidatos[0] if candidatos else items[0]
                args = {"product_id": item["product_id"], "cantidad": 0}
                t0 = time.perf_counter()
                res = self.h.ejecutar("cambiar_cantidad", args)
                t_tools += time.perf_counter() - t0
                ops.append({"paso": 0, "herramienta": "cambiar_cantidad",
                            "argumentos": args, "resultado": res})
                msgs.append({"role": "system", "content": "Resultado de quitar el producto: "
                             + json.dumps(res, ensure_ascii=False)})

        seleccion_posicional = re.search(
            r"\b(?:agrega|anade|pon)\b.{0,35}\b(?:primer|primero|primera)\b",
            actual_norm,
        )
        seleccion_barata = re.search(
            r"\b(?:agrega|agregala|agregalo|anade|pon)\b.{0,35}\bmas barata\b",
            actual_norm,
        )
        if (seleccion_posicional or seleccion_barata) and e.mostrados:
            elegido = (
                min(e.mostrados, key=lambda producto: producto.get("precio", float("inf")))
                if seleccion_barata else e.mostrados[0]
            )
            args = {
                "product_id": elegido["product_id"],
                "cantidad": elegido.get("cantidad_solicitada", 1),
            }
            t0 = time.perf_counter()
            res = self.h.ejecutar("agregar_al_carrito", args)
            t_tools += time.perf_counter() - t0
            ops.append({"paso": 0, "herramienta": "agregar_al_carrito",
                        "argumentos": args, "resultado": res})
            msgs.append({"role": "system", "content": "Resultado de agregar la opción: "
                         + json.dumps(res, ensure_ascii=False)})
            if res.get("ok") and re.search(
                r"\b(?:cotiza|cotizacion|dime el total|dame el total)\b",
                actual_norm,
            ):
                t0 = time.perf_counter()
                cot = self.h.ejecutar("cotizar", {})
                t_tools += time.perf_counter() - t0
                ops.append({"paso": 0, "herramienta": "cotizar",
                            "argumentos": {}, "resultado": cot})
                msgs.append({"role": "system", "content": "Resultado de cotizar: "
                             + json.dumps(cot, ensure_ascii=False)})

        # Cambiar la cantidad de la única línea del carrito es inequívoco en
        # expresiones como "dos en lugar de tres".
        cambia_cantidad = re.search(
            r"\b(?:en lugar de|mejor que sean|mejor que sea)\b", actual_norm
        )
        if cambia_cantidad:
            carrito = self.h.ver_carrito()["carrito"]
            if len(carrito.get("items", [])) == 1:
                item = carrito["items"][0]
                args = {
                    "product_id": item["product_id"],
                    "cantidad": cantidad_mencionada(texto, item["cantidad"]),
                }
                t0 = time.perf_counter()
                res = self.h.ejecutar("cambiar_cantidad", args)
                t_tools += time.perf_counter() - t0
                ops.append({"paso": 0, "herramienta": "cambiar_cantidad",
                            "argumentos": args, "resultado": res})
                msgs.append({"role": "system", "content": "Resultado del cambio de cantidad: "
                             + json.dumps(res, ensure_ascii=False)})
                if res.get("ok") and re.search(r"\b(?:cotiza|cotizacion)\b", actual_norm):
                    t0 = time.perf_counter()
                    cot = self.h.ejecutar("cotizar", {})
                    t_tools += time.perf_counter() - t0
                    ops.append({"paso": 0, "herramienta": "cotizar",
                                "argumentos": {}, "resultado": cot})
                    msgs.append({"role": "system", "content": "Resultado de cotizar: "
                                 + json.dumps(cot, ensure_ascii=False)})

        # Sustitución explícita tras un cambio de stock: buscar con la cantidad
        # pedida, retirar la línea anterior, agregar una alternativa real y
        # volver a cotizar. No confirma el pedido.
        sustitucion = re.search(
            r"\b(?:cambiala|cambialo|sustituyela|sustituyelo)\b.{0,80}\b(?:otra|otro)\b",
            actual_norm,
        )
        if sustitucion:
            carrito = self.h.ver_carrito()["carrito"]
            if len(carrito.get("items", [])) == 1:
                anterior = carrito["items"][0]
                cantidad = cantidad_mencionada(texto, anterior["cantidad"])
                args_buscar = {"consulta": texto, "cantidad": cantidad}
                if e.presupuesto_cent is not None:
                    args_buscar["precio_max"] = e.presupuesto_cent / 100
                t0 = time.perf_counter()
                busqueda = self.h.ejecutar("buscar_productos", args_buscar)
                t_tools += time.perf_counter() - t0
                ops.append({"paso": 0, "herramienta": "buscar_productos",
                            "argumentos": args_buscar, "resultado": busqueda})
                alternativas = [
                    p for p in busqueda.get("resultados", [])
                    if p["product_id"] != anterior["product_id"]
                ]
                if alternativas:
                    quitar = {"product_id": anterior["product_id"], "cantidad": 0}
                    agregar = {"product_id": alternativas[0]["product_id"], "cantidad": cantidad}
                    for nombre, args in (("cambiar_cantidad", quitar),
                                         ("agregar_al_carrito", agregar),
                                         ("cotizar", {})):
                        t0 = time.perf_counter()
                        res = self.h.ejecutar(nombre, args)
                        t_tools += time.perf_counter() - t0
                        ops.append({"paso": 0, "herramienta": nombre,
                                    "argumentos": args, "resultado": res})
                    msgs.append({"role": "system", "content":
                                 "La sustitución y nueva cotización se ejecutaron con IDs reales.\n"
                                 + self.h.resumen_estado()})

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
                msgs.append({
                    "role": "system",
                    "content": (
                        "La llamada anterior era invalida y no se ejecuto. "
                        "Vuelve a emitir una llamada valida con nombre y argumentos "
                        "del esquema; no afirmes que la accion se completo.\n"
                        + self.h.resumen_estado()
                    ),
                })
                continue

            if not llamadas:
                candidata = limpiar_respuesta(out.get("texto", ""))
                pendiente = (
                    accion_sin_respaldo(candidata, ops)
                    or accion_solicitada_pendiente(texto, e.historial, ops)
                )
                if pendiente:
                    msgs.append({"role": "assistant", "content": candidata})
                    msgs.append({
                        "role": "system",
                        "content": (
                            "La respuesta anterior no completo una accion autorizada "
                            "o afirma una accion sin respaldo. "
                            f"Herramienta pendiente: {pendiente}. "
                            "Ejecuta la herramienta con argumentos validos. Solo pide "
                            "aclaracion si falta un dato obligatorio; color o modelo "
                            "opcional no bloquean elegir una opcion ya mostrada. No "
                            "repitas una afirmacion de exito sin evidencia.\n"
                            + self.h.resumen_estado()
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
            # Si el LLM agotó los pasos evitando una búsqueda suficientemente
            # especificada, ejecutamos solo la consulta (nunca una compra) y
            # construimos una respuesta respaldada por stock real.
            intento_compra = re.search(
                r"\b(?:quiero|necesito|busca|buscar|comprar)\b",
                normalizar(texto),
            )
            busqueda_exitosa = any(
                o["herramienta"] == "buscar_productos" and o["resultado"].get("ok")
                for o in ops
            )
            if intento_compra and not busqueda_exitosa:
                args = {
                    "consulta": texto,
                    "cantidad": cantidad_mencionada(texto),
                }
                t0 = time.perf_counter()
                resultado = self.h.ejecutar("buscar_productos", args)
                t_tools += time.perf_counter() - t0
                ops.append({
                    "paso": self.max_pasos + 1,
                    "herramienta": "buscar_productos",
                    "argumentos": args,
                    "resultado": resultado,
                })
                disponibles = resultado.get("resultados", [])
                descartados = resultado.get("descartados", [])
                if disponibles:
                    primero = disponibles[0]
                    respuesta = (
                        f"Encontré {primero['titulo'][:80]} por "
                        f"{primero['precio']:.2f} euros. ¿Quieres esta opción?"
                    )
                elif any(
                    "stock insuficiente" in d.get("motivos", [])
                    for d in descartados
                ):
                    respuesta = "No hay stock suficiente del producto solicitado."
                else:
                    respuesta = "No encontré productos compatibles con esas condiciones."
            else:
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
