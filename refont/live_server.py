from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Any

from .live_plan import LivePlanOptions, build_live_page_plan


def run_live_server(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> None:
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout

    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue
        response = _handle_request(line)
        output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
        output_stream.flush()


def _handle_request(raw: str) -> dict[str, Any]:
    request_id = None
    try:
        request = json.loads(raw)
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if method == "planPage":
            return {
                "id": request_id,
                "result": _plan_page(params),
            }
        if method == "cancel":
            return {
                "id": request_id,
                "result": {"cancelled": True},
            }
        return _error_response(request_id, "method_not_found", f"unknown method: {method}")
    except Exception as error:
        return _error_response(request_id, "invalid_request", str(error))


def _plan_page(params: dict[str, Any]) -> dict[str, Any]:
    pdf_path = _required_string(params, "pdfPath")
    font_path = _required_string(params, "fontPath")
    page_index = _required_int(params, "pageIndex")
    mode = str(params.get("mode") or "conservative")
    if mode not in {"conservative", "normal"}:
        raise ValueError(f"unsupported mode: {mode}")
    cjk_fallback_raw = params.get("cjkFallbackPath")
    cjk_fallback = Path(cjk_fallback_raw).expanduser().resolve() if cjk_fallback_raw else None

    return build_live_page_plan(
        LivePlanOptions(
            input_pdf=Path(pdf_path).expanduser().resolve(),
            target_font=Path(font_path).expanduser().resolve(),
            page_index=page_index,
            cjk_fallback=cjk_fallback,
            mode=mode,
        )
    )


def _required_string(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing string param: {key}")
    return value


def _required_int(params: dict[str, Any], key: str) -> int:
    value = params.get(key)
    if not isinstance(value, int):
        raise ValueError(f"missing integer param: {key}")
    return value


def _error_response(request_id: object, code: str, message: str) -> dict[str, Any]:
    return {
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
