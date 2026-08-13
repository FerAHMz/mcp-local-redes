"""Punto de entrada del servidor: bucle de transporte sobre stdio.

stdout es exclusivamente el canal del protocolo. Cualquier otro byte que se
escriba ahí rompe la sesión con el cliente, por eso todo el logging va a stderr.
"""

import logging
import sys

from servidor import jsonrpc

log = logging.getLogger("mcp")


def configurar_logging():
    nivel = logging.DEBUG if "--verbose" in sys.argv else logging.INFO
    logging.basicConfig(
        stream=sys.stderr,
        level=nivel,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def escribir(mensaje):
    sys.stdout.write(jsonrpc.serializar(mensaje) + "\n")
    # Sin el flush la respuesta se queda en el buffer y el cliente espera para siempre.
    sys.stdout.flush()


def procesar_linea(linea, despachar):
    """Parsea una línea, la despacha y devuelve la respuesta (o None si no hay que responder)."""
    try:
        mensaje = jsonrpc.parsear(linea)
    except jsonrpc.ErrorRPC as e:
        # No hay forma de recuperar el id de un mensaje que no se pudo parsear,
        # así que la respuesta lleva id null como indica la especificación.
        log.warning("mensaje inválido: %s", e.message)
        return jsonrpc.respuesta_error(None, e)

    try:
        result = despachar(mensaje)
    except jsonrpc.ErrorRPC as e:
        if mensaje["es_notificacion"]:
            log.warning("notificación %s falló: %s", mensaje["method"], e.message)
            return None
        return jsonrpc.respuesta_error(mensaje["id"], e)
    except Exception:
        log.exception("error no controlado en %s", mensaje["method"])
        if mensaje["es_notificacion"]:
            return None
        return jsonrpc.respuesta_error(mensaje["id"], jsonrpc.ErrorRPC(jsonrpc.INTERNAL_ERROR))

    # Las notificaciones nunca se responden, aunque el despachador devuelva algo.
    if mensaje["es_notificacion"]:
        return None
    return jsonrpc.respuesta(mensaje["id"], result)


def bucle(despachar, entrada=sys.stdin):
    """Lee stdin línea por línea hasta EOF y escribe cada respuesta en stdout."""
    for linea in entrada:
        linea = linea.strip()
        if not linea:
            continue
        log.debug("<- %s", linea)
        respuesta = procesar_linea(linea, despachar)
        if respuesta is not None:
            log.debug("-> %s", jsonrpc.serializar(respuesta))
            escribir(respuesta)


def _despachar_minimo(mensaje):
    if mensaje["method"] == "ping":
        return {}
    raise jsonrpc.ErrorRPC(jsonrpc.METHOD_NOT_FOUND, data=mensaje["method"])


def main():
    configurar_logging()
    log.info("servidor iniciado")
    bucle(_despachar_minimo)
    log.info("stdin cerrado, termino")


if __name__ == "__main__":
    main()
