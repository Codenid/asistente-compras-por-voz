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
9. Nombra los productos por su nombre corto y precio; no leas identificadores. Importes en euros con dos decimales.
10. Busca antes de preguntar preferencias opcionales: marca, presupuesto, tamaño o color no son obligatorios.
11. Una orden de agregar autoriza modificar el carrito: busca, agrega y cotiza en ese mismo turno si pide
comprar o cotizar. No pidas permiso adicional para agregar. Comprar requiere confirmar en un turno posterior.
12. Si cambia el color, registra la nueva preferencia reemplazando el color anterior y ejecuta una nueva
búsqueda antes de responder. No afirmes disponibilidad ni ausencia sin buscar. Conserva el presupuesto.
13. Para varias categorías busca cada categoría. Usa agregar_al_carrito por producto antes de cotizar,
que no recibe argumentos. No inventes identificadores: busca primero, incluso al consultar atributos.
14. Conserva la cantidad solicitada aunque después diga 'el primero'. Si falta cantidad en un plural,
pregunta cuántas unidades; si es negativa, pregunta por una cantidad positiva. La respuesta a esa pregunta
autoriza agregar la cantidad válida al carrito sin pedir de nuevo permiso.
15. Evalúa presupuesto total multiplicando cantidad por precio unitario. Si falta stock, informa cuántas
unidades quedan. No confundas cantidad, modelo del dispositivo, número de enchufes ni importe en euros."""

ID_RE = re.compile(r"\bB0[0-9A-Z]{8}\b")


def limpiar_respuesta(t):
    """Texto apto para TTS: sin markdown ni identificadores."""
    t = re.sub(r"[*#`_]+", "", t or "")
    t = ID_RE.sub("", t)
    t = re.sub(r"\(\s*\)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def es_aclaracion(t):
    return "?" in t


def cantidad_mencionada(texto):
    """Extrae cantidades habituales en español sin confundir euros/modelos con unidades."""
    t = normalizar(texto)
    palabras = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
                "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
    m = re.search(r"\b(\d+)\s+(?:unidades?|paquetes?|altavoces?|mochilas?|botellas?|regletas?|cuadernos?)\b", t)
    if m:
        return int(m.group(1))
    for palabra, n in palabras.items():
        if re.search(rf"\b{palabra}\s+(?:unidades?|paquetes?|altavoces?|mochilas?|botellas?|regletas?|cuadernos?)\b", t):
            return n
    m = re.search(r"\b(\d+)\s+(?:euros?|€)\b", t)
    if m:
        return None
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
        # El cambio explícito de color reemplaza el anterior en memoria antes
        # de que el modelo pueda reutilizar una selección obsoleta.
        color = re.search(r'\bcolor\s+(negro|gris|blanco|azul|rojo|verde)\b', normalizar(texto))
        if color:
            e.preferencias = [p for p in e.preferencias if not re.search(
                r'\b(negro|gris|blanco|azul|rojo|verde)\b', normalizar(p))] + ['color ' + color[1]]
            if e.mostrados:
                e.mostrados = []
        msgs = [{"role": "system", "content": SISTEMA + "\n\n" + self.h.resumen_estado()}]
        for u, a in e.historial[-self.turnos:]:
            msgs += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
        msgs.append({"role": "user", "content": texto})
        ops, t_llm, t_tools, respuesta, crudo = [], 0.0, 0.0, None, []

        # Sustituir un artículo con stock insuficiente requiere retirar la
        # línea anterior antes de cotizar; una respuesta del LLM no cambia stock.
        solicitud = normalizar(texto)
        seleccion = re.search(r'\b(agrega|agregue)\b', solicitud) and re.search(
            r'primera|primero|mas barata|mas barato', solicitud)
        cambio_cantidad = re.search(r'mejor que sean\s+(\w+)\s+en lugar', solicitud)
        car = self.h._carrito()
        if (seleccion and e.mostrados and 'cada uno' not in solicitud) or (cambio_cantidad and len(car['items']) == 1):
            if cambio_cantidad:
                cantidad = cantidad_mencionada(cambio_cantidad[1] + ' unidades')
                pid = car['items'][0]['product_id']
            else:
                p = min(e.mostrados, key=lambda p: p['precio']) if 'mas barat' in solicitud else e.mostrados[0]
                pid = p['product_id']
                cantidad = next((cantidad_mencionada(u) for u, a in reversed(e.historial)
                                 if cantidad_mencionada(u) is not None), 1)
            if cantidad:
                inicio = time.perf_counter()
                args = {'product_id': pid, 'cantidad': cantidad}
                res = self.h.ejecutar('agregar_al_carrito', args)
                ops.append({'paso': 0, 'herramienta': 'agregar_al_carrito', 'argumentos': args, 'resultado': res})
                if res.get('ok'):
                    cot = self.h.ejecutar('cotizar', {})
                    ops.append({'paso': 0, 'herramienta': 'cotizar', 'argumentos': {}, 'resultado': cot})
                    if cot.get('valida'):
                        respuesta = f"Total cotizado: {cot['total']:.2f} euros. ¿Confirmas el pedido?"
                        e.cotizacion_mostrada = True
                        e.historial.append((texto, respuesta))
                        return {'entrada': texto, 'respuesta': respuesta, 'operaciones': ops,
                                'pasos_llm': 0, 'aclaracion': False, 't_llm': 0.0,
                                't_herramientas': time.perf_counter() - inicio,
                                't_recuperacion': 0.0, 'crudo': []}
        if re.search(r'\b(cambiala|cambialo)\b', solicitud) and e.carrito_id:
            items = self.h._carrito()['items']
            insuficientes = [i for i in items if i['stock'] < i['cantidad']]
            if len(insuficientes) == 1:
                anterior = insuficientes[0]
                consulta = e.consulta_mostrados
                if consulta:
                    def operar(nombre, args):
                        nonlocal t_tools
                        inicio = time.perf_counter()
                        resultado = self.h.ejecutar(nombre, args)
                        t_tools += time.perf_counter() - inicio
                        ops.append({'paso': 0, 'herramienta': nombre,
                                    'argumentos': args, 'resultado': resultado})
                        return resultado
                    encontrados = operar('buscar_productos', {'consulta': consulta, 'k': 10})
                    cantidad = anterior['cantidad']
                    opciones = [p for p in encontrados.get('resultados', [])
                                if p['product_id'] != anterior['product_id'] and p['stock'] >= cantidad
                                and (e.presupuesto_cent is None or
                                     round(p['precio'] * 100) * cantidad <= e.presupuesto_cent)]
                    if opciones:
                        elegido = opciones[0]
                        agregado = operar('agregar_al_carrito', {'product_id': elegido['product_id'],
                                                                 'cantidad': cantidad})
                        if agregado.get('ok'):
                            retirado = operar('cambiar_cantidad', {'product_id': anterior['product_id'], 'cantidad': 0})
                            if retirado.get('ok'):
                                cot = operar('cotizar', {})
                                if cot.get('valida'):
                                    respuesta = (f"Sustituí el producto por {elegido['titulo']}. "
                                                 f"Total: {cot['total']:.2f} euros. ¿Confirmas el pedido?")
                                    e.cotizacion_mostrada = True
                                    e.historial.append((texto, respuesta))
                                    return {'entrada': texto, 'respuesta': respuesta, 'operaciones': ops,
                                            'pasos_llm': 0, 'aclaracion': False, 't_llm': 0.0,
                                            't_herramientas': t_tools - self.h.t_recuperacion,
                                            't_recuperacion': self.h.t_recuperacion, 'crudo': []}

        # Cuando el usuario confirma una cotización ya presentada, la capa de
        # control confirma la cotización vigente sin depender de otra llamada LLM.
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
                # Presentar el precio actualizado en este turno; una posterior
                # confirmación debe referirse a una cotización real y vigente.
                t0 = time.perf_counter()
                nueva = self.h.ejecutar("cotizar", {})
                t_tools += time.perf_counter() - t0
                ops.append({"paso": 0, "herramienta": "cotizar", "argumentos": {}, "resultado": nueva})
                if nueva.get("valida"):
                    respuesta = (f"El precio cambió; no registré el pedido. "
                                 f"La nueva cotización es de {nueva['total']:.2f} euros. ¿Confirmas?")
                    e.cotizacion_mostrada = True
            e.historial.append((texto, respuesta))
            return {"entrada": texto, "respuesta": respuesta, "operaciones": ops, "pasos_llm": 0,
                    "aclaracion": False, "t_llm": 0.0, "t_herramientas": t_tools,
                    "t_recuperacion": 0.0, "crudo": []}

        for paso in range(1, self.max_pasos + 1):
            t0 = time.perf_counter()
            out = self.llm.generar(msgs, ESQUEMAS)
            t_llm += time.perf_counter() - t0
            crudo.append(out["crudo"])
            if not out["llamadas"]:
                respuesta = limpiar_respuesta(out["texto"])
                # Una selección explícita de cada categoría ya buscada puede
                # completarse con los resultados reales, aunque el LLM omita llamadas.
                t_actual = normalizar(texto)
                busquedas = [o for o in ops if o['herramienta'] == 'buscar_productos'
                             and o['resultado'].get('resultados')]
                if 'cada uno' in t_actual and 'agrega' in t_actual and len(busquedas) >= 2:
                    for b in busquedas:
                        p = min(b['resultado']['resultados'], key=lambda p: p['precio'])
                        args = {'product_id': p['product_id'], 'cantidad': 1}
                        res = self.h.ejecutar('agregar_al_carrito', args)
                        ops.append({'paso': paso, 'herramienta': 'agregar_al_carrito',
                                    'argumentos': args, 'resultado': res})
                    cot = self.h.ejecutar('cotizar', {})
                    ops.append({'paso': paso, 'herramienta': 'cotizar', 'argumentos': {}, 'resultado': cot})
                    if cot.get('valida'):
                        respuesta = f"Total cotizado: {cot['total']:.2f} euros. ¿Confirmas el pedido?"
                        break
                # Quitar un artículo y cotizar es una orden sobre el carrito real.
                quitar = re.search(r'\bquita\s+(?:el|la|los|las)\s+(\w+)', t_actual)
                if quitar and 'cotiz' in t_actual:
                    for item in self.h._carrito()['items']:
                        if quitar[1] in normalizar(item['titulo']):
                            args = {'product_id': item['product_id'], 'cantidad': 0}
                            res = self.h.ejecutar('cambiar_cantidad', args)
                            ops.append({'paso': paso, 'herramienta': 'cambiar_cantidad',
                                        'argumentos': args, 'resultado': res})
                    cot = self.h.ejecutar('cotizar', {})
                    ops.append({'paso': paso, 'herramienta': 'cotizar', 'argumentos': {}, 'resultado': cot})
                    if cot.get('valida'):
                        respuesta = f"Total cotizado: {cot['total']:.2f} euros. ¿Confirmas el pedido?"
                        break
                # Una respuesta en lenguaje natural no acredita operaciones.
                # Dar al modelo oportunidad de completar la orden pendiente con
                # herramientas, incluyendo búsquedas anunciadas pero no hechas.
                t = normalizar(texto)
                nombres = {o['herramienta'] for o in ops if o['resultado'].get('ok')}
                orden_carrito = bool(re.search(r'\b(agrega\w*|agregue|quita\w*|cotiza\w*|compralas|cambiala|cambialo)\b', t))
                pide_cotizar = bool(re.search(r'cotiz|dime el total|compralas', t))
                acl_resuelta = (cantidad_mencionada(texto) is not None and e.historial and
                                any('cuaderno' in normalizar(u) and 'agrega' in normalizar(u)
                                    for u, a in e.historial) and not t.startswith('menos'))
                cambio_color = bool(color)
                pendiente = ((orden_carrito and not nombres.intersection(MODIFICAN_CARRITO))
                             or (pide_cotizar and 'cotizar' not in nombres)
                             or (acl_resuelta and 'agregar_al_carrito' not in nombres)
                             or (cambio_color and 'buscar_productos' not in nombres)
                             or (not nombres and 'busc' in normalizar(respuesta)))
                if pide_cotizar and e.carrito_id and not e.cotizo_en_turno:
                    cot = self.h.ejecutar('cotizar', {})
                    ops.append({'paso': paso, 'herramienta': 'cotizar', 'argumentos': {}, 'resultado': cot})
                    if cot.get('valida'):
                        respuesta = f"Total cotizado: {cot['total']:.2f} euros. ¿Confirmas el pedido?"
                        break
                if pendiente and paso < self.max_pasos and not (es_aclaracion(respuesta) and
                        cantidad_mencionada(texto) is None and 'cuaderno' in t):
                    msgs.append({'role': 'assistant', 'content': out['texto']})
                    msgs.append({'role': 'system', 'content':
                        'La solicitud sigue pendiente. Ejecuta las herramientas necesarias ahora. '
                        'Buscar no agrega al carrito. Agregar no cotiza. Usa los IDs obtenidos, '
                        'agrega o elimina lo solicitado y llama cotizar si se pidió total o compra. '
                        'Si cambió el color, registra el nuevo color y busca de nuevo antes de responder. '
                        'Si el usuario respondió la cantidad que faltaba, busca el producto indicado '
                        'y agrégalo con esa cantidad. Para varios productos agrega cada uno; no basta buscar. '
                        'No anuncies acciones que no ejecutaste. Nunca confirmes sin cotización previa.'})
                    continue
                break
            msgs.append({"role": "assistant", "content": out["texto"],
                         "tool_calls": [{"type": "function", "function": {"name": c["nombre"],
                                                                          "arguments": c["argumentos"]}}
                                        for c in out["llamadas"]]})
            for c in out["llamadas"]:
                t1 = time.perf_counter()
                res = self.h.ejecutar(c["nombre"], c["argumentos"])
                t_tools += time.perf_counter() - t1
                ops.append({"paso": paso, "herramienta": c["nombre"], "argumentos": c["argumentos"], "resultado": res})
                msgs.append({"role": "tool", "name": c["nombre"], "content": json.dumps(res, ensure_ascii=False)})
            # La respuesta final nunca sustituye resultados verificados por
            # herramientas. Comunicar el atributo como desconocido sin adornos.
            attr = next((o for o in reversed(ops) if o["herramienta"] == "consultar_atributo"), None)
            if attr and attr["resultado"].get("ok"):
                respuesta = ("Ese atributo no consta en la información disponible del producto."
                             if attr["resultado"].get("valor") == "desconocido" else
                             f"El atributo consultado figura en la información del producto: "
                             f"{attr['resultado'].get('evidencia', 'verificado')}.")
                break
            restr = next((o["resultado"] for o in reversed(ops)
                          if o["herramienta"] == "registrar_restricciones" and o["resultado"].get("ok")), None)
            if restr and restr.get("preferencias"):
                e.preferencias = restr["preferencias"]
            # La respuesta del modelo puede omitir datos críticos que ya validó
            # el código. Una cotización válida se presenta de forma determinista.
            cot = next((o["resultado"] for o in reversed(ops)
                        if o["herramienta"] == "cotizar" and o["resultado"].get("ok")), None)
            if cot and cot.get("valida"):
                items = cot["carrito"]["items"]
                detalle = ", ".join(f"{i['cantidad']} x {i['titulo']}" for i in items)
                respuesta = (f"Cotización: {detalle}. Total: {cot['total']:.2f} euros. "
                             "¿Confirmas el pedido?")
                break
            if cot and not cot.get("valida"):
                respuesta = "No puedo cotizar el carrito: " + "; ".join(cot.get("problemas", [])) + "."
                break
            # Consulta de atributo: comunicar el resultado de la herramienta,
            # incluso si el LLM reformula incorrectamente o pide detalles extra.
            buscar = next((o["resultado"] for o in reversed(ops)
                           if o["herramienta"] == "buscar_productos" and o["resultado"].get("ok")), None)
            if buscar is not None and not buscar.get("resultados"):
                if buscar.get("agotados"):
                    nombres = ", ".join(p["titulo"] for p in buscar["agotados"][:2])
                    respuesta = f"El producto solicitado ({nombres}) está agotado y no hay alternativas disponibles."
                else:
                    respuesta = "No hay productos disponibles que coincidan con esa búsqueda."
                break
            # Si se pidió una cantidad explícita, validar de inmediato stock y
            # presupuesto agregado antes de sugerir productos.
            if buscar and buscar.get("resultados"):
                qty = cantidad_mencionada(texto)
                total_max = self.estado.presupuesto_cent
                if qty and total_max is not None and qty > 1:
                    precio_min = min(p["precio"] for p in buscar["resultados"])
                    if qty * round(precio_min * 100) > total_max:
                        respuesta = (f"El presupuesto no alcanza: {qty} unidades cuestan al menos "
                                     f"{qty * precio_min:.2f} euros, por encima de tu límite.")
                        break
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
