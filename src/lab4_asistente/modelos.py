# ===== LLM local con llamado a herramientas =====
"""Backends del LLM. LLMLocal: transformers + chat template con herramientas (formato Qwen/Hermes <tool_call>).
LLMGuion: respuestas predefinidas, solo para la autoprueba sin modelos."""
import json
import re

TOOL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)


def _llamada(obj):
    if not isinstance(obj, dict) or "name" not in obj:
        return None
    args = obj.get("arguments", obj.get("parameters", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            args = {"_crudo": args}
    return {"nombre": obj["name"], "argumentos": args if isinstance(args, dict) else {}}


def analizar_salida(texto):
    """Extrae llamadas <tool_call>{json}</tool_call>; si no hay, intenta un JSON suelto con 'name'."""
    llamadas = []
    for bloque in TOOL_RE.findall(texto):
        try:
            c = _llamada(json.loads(bloque))
        except json.JSONDecodeError:
            c = None
        llamadas.append(c or {"nombre": "_invalida", "argumentos": {"_crudo": bloque[:200]}})
    limpio = TOOL_RE.sub("", texto).replace("<tool_call>", "").strip()
    if not llamadas and limpio.startswith("{"):
        try:
            c = _llamada(json.loads(limpio))
            if c:
                llamadas, limpio = [c], ""
        except json.JSONDecodeError:
            pass
    return {"texto": limpio, "llamadas": llamadas, "crudo": texto}


class LLMLocal:
    def __init__(self, modelo, cuatro_bits=True, max_tokens=384, dispositivo="cuda", permitir_cpu=True):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(modelo)
        usar_cuda = str(dispositivo).startswith("cuda")
        kw = {"device_map": "auto"} if usar_cuda else {}
        if cuatro_bits and usar_cuda:
            kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                           bnb_4bit_compute_dtype=torch.float16,
                                                           bnb_4bit_use_double_quant=True)
        else:
            kw["torch_dtype"] = torch.float16 if usar_cuda else torch.float32
        try:
            self.model = AutoModelForCausalLM.from_pretrained(modelo, **kw).eval()
        except ValueError as exc:
            falta_vram = usar_cuda and cuatro_bits and (
                "dispatched on the CPU or the disk" in str(exc)
                or "enough GPU RAM" in str(exc)
            )
            if not (permitir_cpu and falta_vram):
                raise
            print("La VRAM disponible no alcanza para el modelo cuantizado; se cargará en CPU.")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            self.model = AutoModelForCausalLM.from_pretrained(
                modelo, torch_dtype=torch.float32, low_cpu_mem_usage=True
            ).eval()
        self.max_tokens = max_tokens

    def generar(self, mensajes, herramientas):
        enc = self.tok.apply_chat_template(mensajes, tools=herramientas, add_generation_prompt=True,
                                           return_dict=True, return_tensors="pt")
        enc = {k: enc[k].to(self.model.device) for k in ("input_ids", "attention_mask") if k in enc}
        with self.torch.inference_mode():
            out = self.model.generate(**enc, max_new_tokens=self.max_tokens, do_sample=False,
                                      temperature=None, top_p=None, top_k=None,
                                      pad_token_id=self.tok.pad_token_id or self.tok.eos_token_id)
        texto = self.tok.decode(out[0, enc["input_ids"].shape[1]:], skip_special_tokens=False)
        for fin in ("<|im_end|>", "<|endoftext|>", "<|eot_id|>", self.tok.eos_token or ""):
            texto = texto.replace(fin, "") if fin else texto
        return analizar_salida(texto.strip())


class LLMGuion:
    """Devuelve salidas predefinidas en orden (texto crudo con <tool_call>)."""
    def __init__(self, salidas):
        self.salidas = list(salidas)

    def generar(self, mensajes, herramientas):
        s = self.salidas.pop(0)
        return analizar_salida(s(mensajes) if callable(s) else s)
