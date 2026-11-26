#!/usr/bin/env python3
"""Audita resultados ya generados por el notebook 07, sin volver a ejecutar modelos.

Busca registros.json debajo de output/escenarios y genera:
  - auditoria_escenarios.csv: una fila por escenario
  - auditoria_turnos.csv: una fila por turno, con diálogo y herramientas
  - auditoria_escenarios.md: resumen legible para revisión

Uso desde la raíz del proyecto:
    python auditar_escenarios.py
    python auditar_escenarios.py --resultados output/escenarios --salida output/auditoria
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_order_count(estado: dict[str, Any] | None, turnos: list[dict[str, Any]]) -> int | str:
    if estado is not None and isinstance(estado.get("pedidos"), list):
        return len(estado["pedidos"])
    # Fallback si no existe estado_final.json.
    count = 0
    for turno in turnos:
        for op in turno.get("operaciones", []):
            result = op.get("resultado", {})
            if op.get("herramienta") == "confirmar_pedido" and result.get("estado") == "registrado":
                count += 1
    return count


def tool_summary(turno: dict[str, Any]) -> str:
    parts = []
    for op in turno.get("operaciones", []):
        name = op.get("herramienta", "?")
        result = op.get("resultado", {})
        status = result.get("estado", result.get("ok", ""))
        detail = result.get("problemas") or result.get("aviso") or ""
        parts.append(f"{name} [{status}]" + (f": {detail}" if detail else ""))
    return " | ".join(parts)


def diagnosis(expected: dict[str, Any], verification: dict[str, Any],
              order_count: int | str) -> str:
    failures = verification.get("fallos", []) or []
    incidents = verification.get("incumplimientos", []) or []
    if verification.get("ok"):
        return "Aprobado por el verificador automático; revisar manualmente solo si se requiere evidencia semántica."
    if incidents:
        return "Posible incumplimiento de una regla obligatoria; revisar operaciones y estado final."
    if expected.get("pedidos") == 0 and order_count == 0:
        phrase_only = failures and all(
            "respuesta no menciona" in str(item).lower() for item in failures
        )
        if phrase_only:
            return "Posible falso negativo: no hubo compra y solo falló la coincidencia literal de la respuesta."
    if any("aclaracion" in str(item).lower() for item in failures):
        return "Revisar manejo de ambigüedad/cantidad: la prueba esperaba una aclaración o una acción concreta."
    if expected.get("pedidos") == 1 and order_count == 0:
        return "La prueba esperaba una compra y no se registró; revisar diálogo, cotización y motivo de bloqueo."
    return "Revisar el detalle: el escenario no alcanzó una o más condiciones esperadas."


def collect(result_root: Path, include_diagnostics: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    scenario_rows: list[dict[str, Any]] = []
    turn_rows: list[dict[str, Any]] = []
    records = sorted(result_root.rglob("registro.json"))
    if not records:
        raise FileNotFoundError(
            f"No encontré registro.json debajo de: {result_root}\n"
            "Ejecuta primero el notebook 07 o indica la carpeta donde guardó output/escenarios."
        )

    for record_path in records:
        # El notebook también guarda ejecuciones de diagnóstico (texto correcto
        # frente a audio y pruebas aisladas). No mezclarlas con el conjunto
        # principal de 14 pruebas de texto + 6 pruebas de voz.
        relative_parts = record_path.relative_to(result_root).parts
        if not include_diagnostics and any(
            part in {"voz_transcripcion_correcta", "diagnostico_texto"}
            for part in relative_parts
        ):
            continue
        try:
            record = load_json(record_path)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"AVISO: no pude leer {record_path}: {exc}")
            continue

        scenario = record.get("escenario", {})
        scenario_id = scenario.get("id", record_path.parent.name)
        mode = record.get("modo", scenario.get("modo", "desconocido"))
        expected = scenario.get("esperado", {})
        turns = record.get("turnos", [])
        verification = record.get("verificacion", {})
        state_path = record_path.with_name("estado_final.json")
        state = load_json(state_path) if state_path.exists() else None
        orders = get_order_count(state, turns)
        failures = verification.get("fallos", []) or []
        incidents = verification.get("incumplimientos", []) or []
        conversation = []

        for turn in turns:
            n = turn.get("turno", "")
            user_text = turn.get("entrada", turn.get("texto_correcto", ""))
            response = turn.get("respuesta", "")
            asr = turn.get("transcripcion_asr", "")
            tools = tool_summary(turn)
            conversation.append(f"T{n}: Usuario: {user_text}\n   Agente: {response}\n   Herramientas: {tools or 'ninguna'}")
            turn_rows.append({
                "escenario": scenario_id,
                "modo": mode,
                "tipo": scenario.get("tipo", ""),
                "turno": n,
                "texto_referencia": turn.get("texto_correcto", ""),
                "transcripcion_asr": asr,
                "entrada_ejecutada": user_text,
                "respuesta_agente": response,
                "aclaracion_detectada": turn.get("aclaracion", ""),
                "herramientas_y_resultado": tools,
                "eventos_inyectados": json_text(turn.get("eventos", [])),
            })

        scenario_rows.append({
            "escenario": scenario_id,
            "ejecucion": str(record_path.parent.relative_to(result_root)),
            "modo": mode,
            "tipo": scenario.get("tipo", ""),
            "esperaba_pedidos": expected.get("pedidos", "no especificado"),
            "pedidos_observados": orders,
            "esperaba_items": json_text(expected.get("items", [])),
            "esperaba_carrito_final": json_text(expected.get("carrito_final", [])),
            "restricciones_esperadas": json_text({k: v for k, v in expected.items()
                                                    if k not in {"pedidos", "items", "carrito_final"}}),
            "aprobado_verificador": verification.get("ok", "sin resultado"),
            "fallos_verificador": " | ".join(map(str, failures)),
            "incumplimientos_reglas": " | ".join(map(str, incidents)),
            "diagnostico_preliminar": diagnosis(expected, verification, orders),
            "ruta_registro": str(record_path),
            "dialogo_completo": "\n".join(conversation),
        })

    return scenario_rows, turn_rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Auditoría de escenarios — Notebook 07",
        "",
        "> Este informe organiza la evidencia existente. El diagnóstico es preliminar: una coincidencia del verificador no sustituye la revisión funcional del diálogo.",
        "",
        f"Escenarios encontrados: **{len(rows)}**. Aprobados automáticamente: **{sum(r['aprobado_verificador'] is True for r in rows)}**. Marcados para revisar: **{sum(r['aprobado_verificador'] is not True for r in rows)}**.",
        "",
    ]
    for row in rows:
        lines.extend([
            f"## {row['escenario']} — {row['tipo']} ({row['modo']})",
            "",
            f"- Resultado del verificador: **{row['aprobado_verificador']}**",
            f"- Pedidos esperados/observados: **{row['esperaba_pedidos']} / {row['pedidos_observados']}**",
            f"- Fallos automáticos: {row['fallos_verificador'] or 'ninguno'}",
            f"- Incumplimientos registrados: {row['incumplimientos_reglas'] or 'ninguno'}",
            f"- Diagnóstico preliminar: {row['diagnostico_preliminar']}",
            "",
            "### Conversación y herramientas",
            "",
            "```text",
            row["dialogo_completo"] or "No hay turnos en el registro.",
            "```",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resultados", type=Path, default=Path("output/escenarios"),
                        help="Carpeta con los registros JSON generados por el notebook 07.")
    parser.add_argument("--salida", type=Path, default=Path("output/auditoria_escenarios"),
                        help="Carpeta donde se guardarán los CSV y el informe Markdown.")
    parser.add_argument("--incluir-diagnosticos", action="store_true",
                        help="Incluye también repeticiones con transcripción correcta y diagnósticos de voz.")
    args = parser.parse_args()
    result_root = args.resultados.expanduser().resolve()
    output_root = args.salida.expanduser().resolve()
    if not result_root.is_dir():
        raise FileNotFoundError(f"No existe la carpeta de resultados: {result_root}")

    scenario_rows, turn_rows = collect(result_root, args.incluir_diagnosticos)
    output_root.mkdir(parents=True, exist_ok=True)
    write_csv(output_root / "auditoria_escenarios.csv", scenario_rows)
    write_csv(output_root / "auditoria_turnos.csv", turn_rows)
    write_markdown(output_root / "auditoria_escenarios.md", scenario_rows)

    passed = sum(row["aprobado_verificador"] is True for row in scenario_rows)
    print(f"Escenarios mapeados: {len(scenario_rows)}")
    print(f"Aprobados por el verificador: {passed}")
    print(f"Requieren revisión: {len(scenario_rows) - passed}")
    print(f"Archivos generados en: {output_root}")
    print("- auditoria_escenarios.csv (resumen y diagnóstico preliminar)")
    print("- auditoria_turnos.csv (diálogo y herramientas, turno por turno)")
    print("- auditoria_escenarios.md (informe legible con evidencia)")


if __name__ == "__main__":
    main()
