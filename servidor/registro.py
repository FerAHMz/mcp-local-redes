"""Registro de herramientas: nombre, descripción, esquema de entrada y función que la ejecuta.

Cada herramienta es un dict con las tres llaves que MCP publica en tools/list
más `ejecutar`, una función (db, argumentos) -> str que nunca sale del servidor.
"""

from servidor import jsonrpc

# Ninguna herramienta devuelve al modelo más filas que esto. Es un tope de
# diseño, no una consecuencia del tamaño de los datos.
MAX_FILAS = 200


class ErrorNegocio(Exception):
    """Fallo de la herramienta que no es del protocolo: placa inexistente, rango vacío, etc.

    Se devuelve como `result` con isError=true para que el modelo pueda
    explicárselo al usuario, en lugar de como error JSON-RPC.
    """


# Importo aquí y no arriba porque los módulos de herramientas dependen de
# MAX_FILAS y ErrorNegocio definidos en este archivo.
from servidor.herramientas import posicion, detenidas, recorrido, kilometraje  # noqa: E402

HERRAMIENTAS = [
    posicion.HERRAMIENTA,
    detenidas.HERRAMIENTA,
    recorrido.HERRAMIENTA,
    kilometraje.HERRAMIENTA,
]

_POR_NOMBRE = {h["name"]: h for h in HERRAMIENTAS}


def listar():
    """Lista para tools/list: solo los campos que define el protocolo."""
    return [{k: h[k] for k in ("name", "description", "inputSchema")} for h in HERRAMIENTAS]


def obtener(nombre):
    return _POR_NOMBRE.get(nombre)


_TIPOS_JSON = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def validar_argumentos(herramienta, argumentos):
    """Valida los argumentos contra el inputSchema; lanza -32602 si no cumplen.

    Cubro lo que usan mis esquemas (tipos básicos, required y enum); no es un
    validador completo de JSON Schema porque no lo necesito.
    """
    esquema = herramienta["inputSchema"]
    if not isinstance(argumentos, dict):
        raise jsonrpc.ErrorRPC(jsonrpc.INVALID_PARAMS, data="'arguments' debe ser un objeto")

    faltantes = [r for r in esquema.get("required", []) if r not in argumentos]
    if faltantes:
        raise jsonrpc.ErrorRPC(jsonrpc.INVALID_PARAMS, data=f"Faltan argumentos requeridos: {', '.join(faltantes)}")

    propiedades = esquema.get("properties", {})
    for nombre, valor in argumentos.items():
        if nombre not in propiedades:
            raise jsonrpc.ErrorRPC(jsonrpc.INVALID_PARAMS, data=f"Argumento desconocido: {nombre}")
        prop = propiedades[nombre]
        tipo = _TIPOS_JSON.get(prop.get("type"))
        # bool es subclase de int en Python; sin este chequeo `true` pasaría como entero.
        if tipo and (not isinstance(valor, tipo) or (isinstance(valor, bool) and prop["type"] != "boolean")):
            raise jsonrpc.ErrorRPC(jsonrpc.INVALID_PARAMS, data=f"'{nombre}' debe ser de tipo {prop['type']}")
        if "enum" in prop and valor not in prop["enum"]:
            raise jsonrpc.ErrorRPC(jsonrpc.INVALID_PARAMS, data=f"'{nombre}' debe ser uno de: {', '.join(map(str, prop['enum']))}")
