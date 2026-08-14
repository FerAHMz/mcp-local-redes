"""Capa MCP: handshake de inicialización, máquina de estados y despacho de métodos."""

import logging

from servidor import jsonrpc

log = logging.getLogger("mcp")

# La primera es la que ofrezco cuando el cliente pide una versión que no conozco.
VERSIONES_SOPORTADAS = ("2025-06-18", "2025-03-26", "2024-11-05")

INFO_SERVIDOR = {"name": "mcp-flota-gt", "version": "1.0.0"}

# Estados de la sesión. El paso de uno a otro lo hacen solo initialize y
# notifications/initialized; cualquier otro método fuera de LISTO se rechaza.
NUEVA = "nueva"
INICIALIZANDO = "inicializando"
LISTA = "lista"


class Sesion:
    """Una sesión MCP sobre una conexión stdio."""

    def __init__(self):
        self.estado = NUEVA
        self.version_protocolo = None
        self.cliente = None
        self._metodos = {
            "initialize": self._initialize,
            "notifications/initialized": self._initialized,
            "ping": self._ping,
        }

    def despachar(self, mensaje):
        """Resuelve un mensaje ya parseado y devuelve el `result` del método."""
        metodo = mensaje["method"]
        manejador = self._metodos.get(metodo)

        if manejador is None:
            if metodo.startswith("notifications/"):
                # Notificaciones que no manejo (por ejemplo notifications/cancelled)
                # se ignoran en silencio: responder a una notificación es un error.
                log.debug("notificación ignorada: %s", metodo)
                return None
            raise jsonrpc.ErrorRPC(jsonrpc.METHOD_NOT_FOUND, data=metodo)

        if metodo != "initialize" and metodo != "ping" and self.estado != LISTA:
            if not (metodo == "notifications/initialized" and self.estado == INICIALIZANDO):
                raise jsonrpc.ErrorRPC(
                    jsonrpc.INVALID_REQUEST,
                    "El servidor no ha sido inicializado",
                    data={"estado": self.estado, "method": metodo},
                )

        return manejador(mensaje["params"])

    def _initialize(self, params):
        if self.estado != NUEVA:
            raise jsonrpc.ErrorRPC(jsonrpc.INVALID_REQUEST, "La sesión ya fue inicializada")
        if not isinstance(params, dict) or "protocolVersion" not in params:
            raise jsonrpc.ErrorRPC(jsonrpc.INVALID_PARAMS, data="Falta 'protocolVersion'")

        pedida = params["protocolVersion"]
        # Si no conozco la versión pedida devuelvo la más reciente que sí soporto
        # y dejo que el cliente decida si continúa o cierra la conexión.
        self.version_protocolo = pedida if pedida in VERSIONES_SOPORTADAS else VERSIONES_SOPORTADAS[0]
        self.cliente = params.get("clientInfo", {})
        self.estado = INICIALIZANDO
        log.info(
            "initialize de %s %s (protocolo %s -> %s)",
            self.cliente.get("name", "?"), self.cliente.get("version", ""), pedida, self.version_protocolo,
        )
        return {
            "protocolVersion": self.version_protocolo,
            "capabilities": {"tools": {}},
            "serverInfo": INFO_SERVIDOR,
        }

    def _initialized(self, params):
        self.estado = LISTA
        log.info("handshake completo, sesión lista")
        return None

    def _ping(self, params):
        return {}
