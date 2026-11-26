# ===== Herramientas, memoria (Estado) y validaciones por codigo =====
"""Herramientas del agente, memoria (Estado) y validaciones por codigo.

Cada herramienta recibe argumentos del LLM, los valida y devuelve un dict JSON con ok / error.
Las etiquetas ESCI no estan aqui: el agente solo ve catalogo + tienda.
"""
import re
import time
from dataclasses import dataclass, field

from .recuperacion import normalizar, tokens
from .tienda import ErrorTienda, euros


NEGACION = re.compile(r"^\s*no\b|\bno (lo |la )?(confirm|compr|quiero)|\bmejor no\b|\bcancel|\bespera\b|\btodavia no\b")
AFIRMACION = re.compile(r"\b(si|confirmo|confirma|confirmar|confirmado|confirmalo|adelante|procede|dale|de acuerdo|"
                        r"ok|okay|vale|compralo|comprala|hazlo|perfecto|correcto)\b")


def es_confirmacion(texto):
    """Consentimiento explicito del usuario (validacion por codigo, no por el LLM)."""
    t = normalizar(texto)
    return bool(AFIRMACION.search(t)) and not NEGACION.search(t)


@dataclass
class Estado:
    presupuesto_cent: int = None
    preferencias: list = field(default_factory=list)
    carrito_id: int = None
    cotizacion: dict = None            # ultima cotizacion {cotizacion_id, total_cent, valida}
    cotizacion_mostrada: bool = False  # se presento al usuario en un turno anterior
    cotizo_en_turno: bool = False
    pedidos: list = field(default_factory=list)
    mostrados: list = field(default_factory=list)   # ultimos productos presentados
    texto_usuario: str = ""
    historial: list = field(default_factory=list)   # [(usuario, asistente)]


def _f(x):
    return None if x is None else euros(x)


ESQUEMAS = [
    {"type": "function", "function": {
        "name": "buscar_productos",
        "description": "Busca productos en el catalogo (RAG). Devuelve titulo, marca, color, precio y existencias.",
        "parameters": {"type": "object", "properties": {
            "cantidad": {"type": "integer", "description": "Unidades deseadas. Recupera la cantidad del mensaje o historial; si no esta clara, pregunta."},
            "consulta": {"type": "string", "description": "Descripcion del producto en palabras clave"},
            "precio_max": {"type": "number", "description": "Precio unitario maximo en euros (opcional)"},
            "k": {"type": "integer", "description": "Cantidad de resultados (1 a 10)"}},
            "required": ["consulta", "cantidad"]}}},
    {"type": "function", "function": {
        "name": "ver_producto",
        "description": "Detalle de un producto: descripcion, caracteristicas, marca, color, precio y existencias.",
        "parameters": {"type": "object", "properties": {"product_id": {"type": "string"}},
                       "required": ["product_id"]}}},
    {"type": "function", "function": {
        "name": "consultar_atributo",
        "description": "Verifica si un atributo (p. ej. 'resistente al agua', '500 ml') aparece en la informacion "
                       "del producto. Si no aparece, el atributo es desconocido.",
        "parameters": {"type": "object", "properties": {"product_id": {"type": "string"},
                                                        "atributo": {"type": "string"}},
                       "required": ["product_id", "atributo"]}}},
    {"type": "function", "function": {
        "name": "registrar_restricciones",
        "description": "Guarda en memoria el presupuesto total maximo y/o las preferencias del usuario. "
                       "preferencias reemplaza la lista completa.",
        "parameters": {"type": "object", "properties": {
            "presupuesto_max": {"type": "number", "description": "Presupuesto total en euros"},
            "preferencias": {"type": "array", "items": {"type": "string"}}}}}},
    {"type": "function", "function": {
        "name": "agregar_al_carrito",
        "description": "Fija la cantidad total deseada; repetir la misma llamada no duplica unidades.",
        "parameters": {"type": "object", "properties": {"product_id": {"type": "string"},
                                                        "cantidad": {"type": "integer"}},
                       "required": ["product_id", "cantidad"]}}},
    {"type": "function", "function": {
        "name": "cambiar_cantidad",
        "description": "Fija la cantidad de un producto del carrito. 0 lo elimina.",
        "parameters": {"type": "object", "properties": {"product_id": {"type": "string"},
                                                        "cantidad": {"type": "integer"}},
                       "required": ["product_id", "cantidad"]}}},
    {"type": "function", "function": {
        "name": "ver_carrito", "description": "Contenido del carrito y total.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "cotizar",
        "description": "Calcula la cotizacion del carrito y valida existencias y presupuesto. "
                       "Presenta el total y pide confirmacion al usuario.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "confirmar_pedido",
        "description": "Registra el pedido de la ultima cotizacion. Solo si el usuario confirmo explicitamente "
                       "la cotizacion en su ultimo mensaje.",
        "parameters": {"type": "object", "properties": {}}}},
]
MODIFICAN_CARRITO = {"agregar_al_carrito", "cambiar_cantidad", "confirmar_pedido"}


class Herramientas:
    def __init__(self, catalogo, recuperador, tienda, k_resultados=5, metodo="sistema"):
        self.cat = catalogo.set_index("product_id")
        self.rec, self.tienda, self.k, self.metodo = recuperador, tienda, k_resultados, metodo
        self.estado = Estado()
        self.t_recuperacion = 0.0

    # --- utilidades ---
    def _existe(self, pid):
        if not isinstance(pid, str) or pid not in self.cat.index:
            raise ErrorTienda(f"product_id desconocido: {pid!r}. Usa un id devuelto por buscar_productos")

    @staticmethod
    def _numero(x, nombre):
        if isinstance(x, str):
            try:
                x = float(x.replace(",", ".").replace("€", "").strip())
            except ValueError:
                pass
        if isinstance(x, bool) or not isinstance(x, (int, float)) or x <= 0:
            raise ErrorTienda(f"{nombre} debe ser un numero positivo")
        return float(x)

    @staticmethod
    def _entero(x, nombre="cantidad"):
        if isinstance(x, str) and x.strip().lstrip("-").isdigit():
            x = int(x)
        if isinstance(x, float) and x.is_integer():
            x = int(x)
        if x is None:
            raise ErrorTienda(f"falta {nombre}: pregunta al usuario cuantas unidades quiere")
        if not isinstance(x, int) or isinstance(x, bool):
            raise ErrorTienda(f"{nombre} debe ser un numero entero")
        return x

    def _ficha(self, pid, extra=None):
        r = self.cat.loc[pid]
        ps = self.tienda.producto(pid)
        d = {"product_id": pid, "titulo": r["titulo"][:140], "marca": r["marca"] or "desconocido",
             "color": r["color"] or "desconocido", "precio": euros(ps["precio_cent"]), "stock": ps["stock"],
             "disponible": ps["stock"] > 0}
        return {**d, **(extra or {})}

    def _carrito(self):
        e = self.estado
        if e.carrito_id is None:
            return {"items": [], "total": 0.0}
        car = self.tienda.carrito(e.carrito_id)
        return {"items": [{"product_id": i["product_id"], "titulo": self.cat.loc[i["product_id"], "titulo"][:80],
                           "cantidad": i["cantidad"], "precio": euros(i["precio_cent"]), "stock": i["stock"],
                           "subtotal": euros(i["subtotal_cent"])} for i in car["items"]],
                "total": euros(car["total_cent"])}

    def _carrito_abierto(self):
        e = self.estado
        if e.carrito_id is None or self.tienda.carrito(e.carrito_id)["estado"] != "abierto":
            e.carrito_id = self.tienda.nuevo_carrito()
        return e.carrito_id

    def _invalidar_cotizacion(self):
        self.estado.cotizacion_mostrada = self.estado.cotizo_en_turno = False

    # --- herramientas ---
    def buscar_productos(self, consulta, cantidad=None, precio_max=None, k=None):
        if not isinstance(consulta, str) or not consulta.strip():
            raise ErrorTienda("consulta vacia")
        cantidad = self._entero(cantidad)
        if cantidad < 1:
            raise ErrorTienda("cantidad debe ser un entero positivo")
        k = min(max(self._entero(k if k is not None else self.k, "k"), 1), 10)
        limite_unitario = None
        if precio_max is not None:
            limite_unitario = int(round(self._numero(precio_max, "precio_max") * 100))

        carrito = self._carrito()
        total_actual = int(round(carrito["total"] * 100))
        subtotales = {
            item["product_id"]: int(round(item["subtotal"] * 100))
            for item in carrito["items"]
        }
        consulta_tokens = set(tokens(consulta))
        genericos = {
            "producto", "productos", "opcion", "opciones", "comprar",
            "quiero", "necesito", "busca", "buscar", "ahora", "color", "marca",
            "maximo", "euros", "mejor", "mismo", "misma", "presupuesto",
            "sea", "sean", "para", "uno", "una", "dos", "tres", "cuatro",
            "cinco", "seis", "siete", "ocho", "nueve", "diez",
            "cambia", "cambiala", "cambialo", "otra", "otro", "tenga",
            "unidades", "disponibles", "dame", "nueva", "nuevo", "cotizacion",
        }
        obligatorios = {
            t for t in consulta_tokens
            if re.search(r"[a-z]", t) and re.search(r"\d", t)
        }
        # Marca y color explícitos son restricciones, no simples señales de
        # ranking. Evita ofrecer un espejo para una consulta H7 o reutilizar
        # resultados grises después de que el usuario pidió negro.
        for columna in ("marca", "color"):
            for valor in self.cat[columna].dropna().astype(str).unique():
                valor_tokens = {
                    t for t in tokens(valor)
                    if len(t) >= 3 and t not in genericos
                }
                if valor_tokens and valor_tokens <= consulta_tokens:
                    obligatorios.update(valor_tokens)
        # Conserva también la categoría principal de la consulta. Debe existir
        # en algún título del catálogo; así "regleta Aigostar" no devuelve una
        # freidora de esa marca y "bombillas H7" no devuelve un espejo LED.
        for termino in tokens(consulta):
            if termino in genericos or len(termino) < 3:
                continue
            aparece_en_titulo = self.cat["titulo"].astype(str).map(
                lambda titulo: termino in set(tokens(titulo))
            ).any()
            if aparece_en_titulo:
                obligatorios.add(termino)
                break
        t0 = time.perf_counter()
        indices = self.rec.buscar(consulta, k=30, metodo=self.metodo)
        self.t_recuperacion += time.perf_counter() - t0
        resultados, descartados = [], []
        for indice in indices:
            pid = self.rec.ids[indice]
            ficha = self._ficha(pid)
            producto = self.tienda.producto(pid)
            precio_cent = producto["precio_cent"]
            total_propuesto = total_actual - subtotales.get(pid, 0) + precio_cent * cantidad
            motivos = []
            ficha_tokens = set(tokens(" ".join([
                str(ficha["titulo"]), str(ficha["marca"]), str(ficha["color"])
            ])))
            if obligatorios and not obligatorios <= ficha_tokens:
                motivos.append(
                    "no coincide con marca, color o modelo solicitado: "
                    + ", ".join(sorted(obligatorios - ficha_tokens))
                )
            if producto["stock"] < cantidad:
                motivos.append("stock insuficiente")
            if limite_unitario is not None and precio_cent > limite_unitario:
                motivos.append("supera el precio unitario maximo")
            presupuesto = self.estado.presupuesto_cent
            if presupuesto is not None and total_propuesto > presupuesto:
                motivos.append("supera el presupuesto total")
            if motivos:
                descartados.append({**ficha, "motivos": motivos})
                continue
            resultados.append({
                "posicion": len(resultados) + 1, **ficha,
                "cantidad_solicitada": cantidad,
                "subtotal": euros(precio_cent * cantidad),
                "total_carrito_propuesto": euros(total_propuesto),
            })
            if len(resultados) >= k:
                break
        self.estado.mostrados = resultados
        return {
            "ok": True, "resultados": resultados, "descartados": descartados[:3],
            "nota": (
                "Opciones compatibles con cantidad, stock y presupuesto."
                if resultados else
                "No hay opciones compatibles entre los candidatos recuperados. "
                "Explica los motivos; pregunta si desea cambiar restricciones."
            ),
        }

    def ver_producto(self, product_id):
        self._existe(product_id)
        r = self.cat.loc[product_id]
        return {"ok": True, **self._ficha(product_id, {
            "descripcion": r["descripcion"][:500] or "desconocido",
            "caracteristicas": r["caracteristicas"][:500] or "desconocido"})}

    def consultar_atributo(self, product_id, atributo):
        self._existe(product_id)
        r = self.cat.loc[product_id]
        texto = " ".join([r["titulo"], r["marca"], r["color"], r["caracteristicas"], r["descripcion"]])
        objetivo = tokens(atributo)
        if not objetivo:
            raise ErrorTienda("atributo vacio")
        for frase in re.split(r"(?<=[.;\n])\s+", texto):
            if all(t in tokens(frase) for t in objetivo):
                return {"ok": True, "atributo": atributo, "valor": "verificado", "evidencia": frase[:200]}
        return {"ok": True, "atributo": atributo, "valor": "desconocido",
                "nota": "no aparece en la informacion del producto; no afirmes ni niegues el atributo"}

    def registrar_restricciones(self, presupuesto_max=None, preferencias=None):
        e = self.estado
        if presupuesto_max is not None:
            e.presupuesto_cent = int(round(self._numero(presupuesto_max, "presupuesto_max") * 100))
        if preferencias is not None:
            if not isinstance(preferencias, list) or not all(isinstance(p, str) for p in preferencias):
                raise ErrorTienda("preferencias debe ser una lista de textos")
            e.preferencias = [p.strip() for p in preferencias if p.strip()]
        return {"ok": True, "presupuesto_max": _f(e.presupuesto_cent), "preferencias": e.preferencias}

    def _fijar(self, product_id, cantidad):
        cid = self._carrito_abierto()
        anterior = next(
            (i["cantidad"] for i in self.tienda.carrito(cid)["items"]
             if i["product_id"] == product_id),
            0,
        )
        self.tienda.fijar_cantidad(cid, product_id, cantidad)
        self._invalidar_cotizacion()
        car = self._carrito()
        out = {"ok": True, "carrito": car}
        p = self.estado.presupuesto_cent
        if p is not None and car["total"] * 100 > p:
            # No dejar que el carrito quede en un estado que viola una
            # restricción explícita; la cotización y la confirmación también
            # revalidan, pero este bloqueo evita continuar con una cotización
            # inválida.
            self.tienda.fijar_cantidad(cid, product_id, anterior)
            raise ErrorTienda(
                f"el total {car['total']} supera el presupuesto {_f(p)}"
            )
        return out

    def agregar_al_carrito(self, product_id, cantidad=None):
        self._existe(product_id)
        cantidad = self._entero(cantidad)
        if cantidad < 1:
            raise ErrorTienda("la cantidad total debe ser un entero positivo")
        # La cantidad es el total deseado, no un incremento. Una llamada repetida es segura.
        return self._fijar(product_id, cantidad)

    def cambiar_cantidad(self, product_id, cantidad=None):
        self._existe(product_id)
        cantidad = self._entero(cantidad)
        if product_id not in {i["product_id"] for i in self._carrito()["items"]}:
            raise ErrorTienda("ese producto no esta en el carrito")
        return self._fijar(product_id, cantidad)

    def ver_carrito(self):
        return {"ok": True, "carrito": self._carrito(), "presupuesto_max": _f(self.estado.presupuesto_cent)}

    def cotizar(self):
        e = self.estado
        if e.carrito_id is None:
            raise ErrorTienda("el carrito esta vacio")
        c = self.tienda.cotizar(e.carrito_id, e.presupuesto_cent)
        e.cotizacion = {"cotizacion_id": c["cotizacion_id"], "total_cent": c["total_cent"], "valida": c["valida"]}
        e.cotizo_en_turno = c["valida"]
        return {"ok": True, "cotizacion_id": c["cotizacion_id"], "carrito": self._carrito(),
                "total": euros(c["total_cent"]), "presupuesto_max": _f(e.presupuesto_cent),
                "valida": c["valida"], "problemas": c["problemas"],
                "siguiente_paso": "presenta el total y pide confirmacion" if c["valida"]
                else "explica los problemas y propone una solucion"}

    def confirmar_pedido(self):
        e = self.estado
        if e.cotizacion is None:
            raise ErrorTienda("no hay cotizacion: arma el carrito y usa cotizar primero")
        ya = any(p["cotizacion_id"] == e.cotizacion["cotizacion_id"] for p in e.pedidos)
        if not ya and not (e.cotizacion_mostrada and es_confirmacion(e.texto_usuario)):
            raise ErrorTienda("el usuario no confirmo explicitamente la cotizacion vigente: presentala y pide "
                              "confirmacion antes de registrar el pedido")
        r = self.tienda.confirmar(e.cotizacion["cotizacion_id"], e.presupuesto_cent)
        if r["estado"] == "rechazado":
            self._invalidar_cotizacion()
            return {"ok": False, "estado": "rechazado", "problemas": r["problemas"], "carrito": self._carrito(),
                    "siguiente_paso": "explica el problema y propone una alternativa; vuelve a cotizar"}
        if r["estado"] == "registrado":
            e.pedidos.append({"pedido_id": r["pedido_id"], "cotizacion_id": r["cotizacion_id"],
                              "total_cent": r["total_cent"]})
            e.carrito_id = None
        return {"ok": True, "estado": r["estado"], "pedido_id": r["pedido_id"], "total": euros(r["total_cent"]),
                "nota": "pedido ya registrado antes; no se duplico" if r["estado"] == "ya_registrado" else
                "pedido registrado e inventario actualizado"}

    # --- despacho ---
    def ejecutar(self, nombre, argumentos):
        fn = getattr(self, nombre, None) if nombre in {s["function"]["name"] for s in ESQUEMAS} else None
        if fn is None:
            return {"ok": False, "error": f"herramienta desconocida: {nombre}"}
        if not isinstance(argumentos, dict):
            return {"ok": False, "error": "argumentos deben ser un objeto JSON"}
        try:
            return fn(**argumentos)
        except TypeError as ex:
            return {"ok": False, "error": f"argumentos invalidos: {ex}"}
        except ErrorTienda as ex:
            return {"ok": False, "error": str(ex)}

    def resumen_estado(self):
        """Memoria que se inyecta en cada turno (sobrevive aunque el historial se recorte)."""
        e = self.estado
        lin = ["ESTADO ACTUAL (memoria del sistema):",
               f"- Presupuesto total maximo: {_f(e.presupuesto_cent) or 'no indicado'} euros",
               f"- Preferencias: {', '.join(e.preferencias) or 'ninguna'}"]
        car = self._carrito()
        if car["items"]:
            lin.append(f"- Carrito (total {car['total']} euros):")
            lin += [f"  * {i['product_id']} | {i['titulo']} | {i['cantidad']} x {i['precio']} | stock {i['stock']}"
                    for i in car["items"]]
        else:
            lin.append("- Carrito: vacio")
        if e.cotizacion:
            lin.append(f"- Ultima cotizacion: {e.cotizacion['cotizacion_id']} total {_f(e.cotizacion['total_cent'])} "
                       f"(valida: {'si' if e.cotizacion['valida'] else 'no'}; mostrada al usuario: "
                       f"{'si' if e.cotizacion_mostrada else 'no'})")
        if e.pedidos:
            lin.append("- Pedidos confirmados: " + ", ".join(f"{p['pedido_id']} ({p['cotizacion_id']}, "
                                                            f"{_f(p['total_cent'])})" for p in e.pedidos))
        if e.mostrados:
            lin.append("- Productos mostrados en la ultima busqueda:")
            lin += [f"  {m['posicion']}) {m['product_id']} | {m['titulo'][:90]} | {m['precio']} euros | "
                    f"stock {m['stock']}" for m in e.mostrados]
        return "\n".join(lin)
