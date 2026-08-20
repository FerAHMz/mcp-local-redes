# Implementación del protocolo MCP

Este documento describe cómo implementé MCP sobre `stdio` y muestra la traza de
una sesión real contra mi servidor. Todos los mensajes de abajo los capturé
corriendo `python -m servidor.main` y escribiéndole directamente a stdin; no
están editados salvo donde indico que recorté por longitud.

## Capas

Separé el código en tres capas que se corresponden con tres niveles del protocolo:

| Capa | Archivo | Responsabilidad |
|---|---|---|
| Transporte | `servidor/main.py` | Leer stdin línea por línea, escribir en stdout con `flush()`, mandar todo log a stderr, cerrar limpio en EOF |
| JSON-RPC 2.0 | `servidor/jsonrpc.py` | Parsear y validar mensajes, distinguir request de notificación, armar respuestas y errores con los códigos estándar |
| MCP | `servidor/protocolo.py` | Handshake `initialize` / `notifications/initialized`, máquina de estados, `ping`, `tools/list`, `tools/call` |

La capa JSON-RPC no sabe nada de MCP y la capa MCP no sabe nada de stdin ni de
stdout. Lo hice así porque facilita probar cada una por separado: las pruebas
del protocolo alimentan el bucle con un `StringIO` en lugar de stdin real, y
las pruebas de la sesión llaman a `Sesion.despachar` con mensajes ya parseados.

## Transporte

Un mensaje es una línea de texto terminada en `\n` que contiene un objeto JSON.
El servidor lee con `for linea in sys.stdin`, procesa y escribe la respuesta
seguida de `\n` y `sys.stdout.flush()`. Sin el `flush` la respuesta se queda en
el buffer de Python y el cliente se bloquea esperando.

stdout es exclusivo del protocolo. Cualquier `print` de depuración ahí rompe la
sesión porque el cliente intentaría parsearlo como JSON. Por eso todo el logging
está configurado sobre stderr desde el arranque.

Cuando stdin llega a EOF el bucle termina, se cierra la conexión a SQLite y el
proceso sale con código 0.

## Tipos de mensaje

- **Request**: tiene `jsonrpc`, `id`, `method` y opcionalmente `params`. Siempre recibe respuesta.
- **Notification**: igual que un request pero **sin** `id`. Nunca recibe respuesta. La distinción la hago con `"id" in mensaje`, no con `mensaje.get("id")`, porque `"id": null` es un request válido según la especificación.
- **Response**: `jsonrpc`, el mismo `id` del request, y `result` **o** `error`, nunca los dos.
- **Error**: objeto con `code`, `message` y opcionalmente `data`.

Códigos que uso:

| Código | Significado | Cuándo lo devuelvo |
|---|---|---|
| `-32700` | Parse error | La línea no es JSON válido. El `id` va en `null` porque no hay forma de recuperarlo |
| `-32600` | Invalid Request | Falta `jsonrpc: "2.0"`, `method` no es cadena, `params` no es objeto ni arreglo, o el método llega antes del handshake |
| `-32601` | Method not found | Un método que el servidor no implementa |
| `-32602` | Invalid params | Herramienta desconocida, argumentos faltantes, de tipo equivocado o fuera del `enum` |
| `-32603` | Internal error | Una excepción no controlada dentro de un manejador |

## Máquina de estados

```
            initialize              notifications/initialized
  NUEVA ───────────────► INICIALIZANDO ───────────────────────► LISTA
```

- En `NUEVA` solo acepto `initialize` y `ping`.
- En `INICIALIZANDO` solo acepto `notifications/initialized` y `ping`.
- En `LISTA` acepto todo menos un segundo `initialize`.

Cualquier otro método fuera de su estado devuelve `-32600` con el estado actual
en `data`, para que en la demo se vea por qué se rechazó.

Sobre la versión del protocolo: si el cliente pide una que soporto, respondo la
misma; si pide una que no, respondo la más reciente que sí soporto y dejo que el
cliente decida si continúa o cierra.

## Errores de protocolo contra errores de negocio

Esta distinción me pareció la más importante del diseño de `tools/call`:

- Si la herramienta **no existe** o los **argumentos están mal formados**, es un error del protocolo y va como objeto `error` JSON-RPC (`-32602`). El modelo hizo algo mal al construir la llamada.
- Si la herramienta existe, los argumentos son válidos, pero el **resultado es un fallo de negocio** (placa inexistente, día sin datos, geocerca ambigua), va como `result` normal con `isError: true` y un mensaje legible. El modelo hizo todo bien y la respuesta es "eso que pides no existe", que es información útil para el usuario.

Internamente las herramientas lanzan `ErrorNegocio` y `protocolo.py` lo convierte en la segunda forma.

## Traza de una sesión completa

Cliente → servidor marcado con `->`, servidor → cliente con `<-`.

### 1. `initialize`

```
-> {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"cliente_prueba","version":"1.0.0"}}}
<- {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"serverInfo":{"name":"mcp-flota-gt","version":"1.0.0"}}}
```

### 2. `notifications/initialized`

```
-> {"jsonrpc":"2.0","method":"notifications/initialized"}
```

No hay línea `<-`: es una notificación y el servidor no responde nada.

### 3. `tools/list`

```
-> {"jsonrpc":"2.0","id":2,"method":"tools/list"}
<- {"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"posicion_actual","description":"Devuelve la última posición reportada por una unidad de la flota: dirección o referencia, coordenadas, velocidad, rumbo, estado del motor y hora del último reporte. Úsala para preguntas como '¿dónde está la P-123BCD?' o '¿se está moviendo la unidad X?'.","inputSchema":{"type":"object","properties":{"placa":{"type":"string","description":"Placa de la unidad, por ejemplo P-123BCD"}},"required":["placa"]}}, ...cinco herramientas más... ]}}
```

Recorté las otras cinco herramientas; tienen la misma forma. La descripción es
lo único que el modelo lee para decidir cuál usar, por eso cada una incluye
ejemplos de las preguntas que responde.

### 4. `tools/call` con resultado correcto

```
-> {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"verificar_geocerca","arguments":{"placa":"P-456DEF","nombre_geocerca":"CEDIS Zona 12","fecha":"2026-08-18"}}}
<- {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{\n  \"placa\": \"P-456DEF\",\n  \"geocerca\": \"CEDIS Zona 12\",\n  \"tipo_geocerca\": \"bodega\",\n  \"fecha\": \"2026-08-18\",\n  \"entro\": true,\n  \"numero_visitas\": 6,\n  \"minutos_total_dentro\": 142,\n  \"visitas\": [\n    {\n      \"entrada\": \"08:08\",\n      \"salida\": \"08:14\",\n      \"minutos_dentro\": 6,\n      \"desde_inicio_del_dia\": true,\n      \"sigue_dentro\": false\n    },\n    {\n      \"entrada\": \"09:39\",\n      \"salida\": \"10:18\",\n      \"minutos_dentro\": 39,\n      \"desde_inicio_del_dia\": false,\n      \"sigue_dentro\": false\n    }, ...cuatro visitas más... ]\n}"}]}}
```

El texto de la herramienta es JSON serializado dentro de la cadena `text`; el
modelo lo lee como texto y lo explica en lenguaje natural.

### 5. `tools/call` con error de negocio

```
-> {"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"posicion_actual","arguments":{"placa":"P-000XXX"}}}
<- {"jsonrpc":"2.0","id":4,"result":{"content":[{"type":"text","text":"No existe la placa P-000XXX. Placas registradas: P-112GHK, P-123BCD, P-223LMN, P-234KLM, P-334PQR, P-345VWX, P-445STV, P-456DEF, P-556WXY, P-567NPQ, P-667ZBC, P-678YZB, P-789GHJ, P-890RST, P-901CDF"}],"isError":true}}
```

Es un `result`, no un `error`: la llamada fue válida, la placa es la que no existe.

### 6. `tools/call` con argumentos inválidos

```
-> {"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"resumen_recorrido","arguments":{"placa":"P-456DEF"}}}
<- {"jsonrpc":"2.0","id":5,"error":{"code":-32602,"message":"Invalid params","data":"Faltan argumentos requeridos: fecha"}}
```

### 7. Método inexistente

```
-> {"jsonrpc":"2.0","id":6,"method":"recursos/listar"}
<- {"jsonrpc":"2.0","id":6,"error":{"code":-32601,"message":"Method not found","data":"recursos/listar"}}
```

### 8. `ping`

```
-> {"jsonrpc":"2.0","id":7,"method":"ping"}
<- {"jsonrpc":"2.0","id":7,"result":{}}
```

## Otros casos de error

Método antes del handshake, en una sesión nueva:

```
-> {"jsonrpc":"2.0","id":1,"method":"tools/list"}
<- {"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"El servidor no ha sido inicializado","data":{"estado":"nueva","method":"tools/list"}}}
```

Línea que no es JSON:

```
-> {no es json}
<- {"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error","data":"Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"}}
```

## Cómo reproducir la traza

```bash
python cliente_prueba.py --demo
```

El cliente imprime en azul lo que envía y en verde lo que recibe, exactamente
como viaja por los pipes. En modo interactivo (`python cliente_prueba.py` sin
argumentos) se puede invocar cada herramienta a mano y mandar `ping`.
