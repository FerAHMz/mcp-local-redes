"""Construcción y validación de mensajes JSON-RPC 2.0.

Esta capa no sabe nada de MCP: solo entiende requests, notificaciones,
respuestas y errores tal como los define la especificación JSON-RPC 2.0.
"""

import json

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

_MENSAJES = {
    PARSE_ERROR: "Parse error",
    INVALID_REQUEST: "Invalid Request",
    METHOD_NOT_FOUND: "Method not found",
    INVALID_PARAMS: "Invalid params",
    INTERNAL_ERROR: "Internal error",
}


class ErrorRPC(Exception):
    """Error que se convierte en un objeto `error` de JSON-RPC al responder."""

    def __init__(self, code, message=None, data=None):
        super().__init__(message or _MENSAJES.get(code, "Error"))
        self.code = code
        self.message = message or _MENSAJES.get(code, "Error")
        self.data = data

    def a_dict(self):
        error = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


def parsear(linea):
    """Convierte una línea de texto en un mensaje validado.

    Devuelve un dict con `method`, `params` y `id` (None si es notificación).
    Lanza ErrorRPC con -32700 si no es JSON y con -32600 si no es un request válido.
    """
    try:
        mensaje = json.loads(linea)
    except json.JSONDecodeError as e:
        raise ErrorRPC(PARSE_ERROR, data=str(e))

    if not isinstance(mensaje, dict):
        raise ErrorRPC(INVALID_REQUEST, data="El mensaje debe ser un objeto JSON")
    if mensaje.get("jsonrpc") != "2.0":
        raise ErrorRPC(INVALID_REQUEST, data="Falta 'jsonrpc': '2.0'")
    if not isinstance(mensaje.get("method"), str):
        raise ErrorRPC(INVALID_REQUEST, data="'method' debe ser una cadena")

    params = mensaje.get("params")
    if params is not None and not isinstance(params, (dict, list)):
        raise ErrorRPC(INVALID_REQUEST, data="'params' debe ser objeto o arreglo")

    # La especificación permite id numérico, de cadena o null. Un id ausente
    # es lo que distingue a una notificación de un request.
    id_ = mensaje.get("id")
    if "id" in mensaje and not isinstance(id_, (str, int, float, type(None))):
        raise ErrorRPC(INVALID_REQUEST, data="'id' debe ser número, cadena o null")

    return {
        "method": mensaje["method"],
        "params": params if params is not None else {},
        "id": id_,
        "es_notificacion": "id" not in mensaje,
    }


def respuesta(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def respuesta_error(id_, error):
    """Arma una respuesta de error. `error` es un ErrorRPC."""
    return {"jsonrpc": "2.0", "id": id_, "error": error.a_dict()}


def serializar(mensaje):
    """Serializa en una sola línea; el transporte delimita mensajes por salto de línea."""
    return json.dumps(mensaje, ensure_ascii=False, separators=(",", ":"))
