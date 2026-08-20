# Servidor MCP local para telemetría de flota

Proyecto 1 del curso **CC3067 Redes**, sección 10, Universidad del Valle de Guatemala.
Fernando Hernández.

Un servidor MCP (Model Context Protocol) que corre en la máquina del operador y
expone las consultas de telemetría de una flota vehicular como herramientas que
un modelo de lenguaje puede invocar. Con él, un chatbot responde preguntas como
"¿dónde está la P-123BCD?" o "¿qué unidad recorrió más kilómetros esta semana?"
sin que el usuario abra la plataforma de rastreo.

El protocolo está implementado desde cero sobre `stdio` con la librería estándar
de Python. No uso el SDK de MCP ni ninguna librería que maneje JSON-RPC; ese es
el requisito central del proyecto y lo explico en la sección
[Implementación del protocolo](#implementación-del-protocolo).

## Qué es MCP

MCP es un protocolo de capa de aplicación que estandariza cómo un modelo de
lenguaje descubre e invoca herramientas externas. Un servidor MCP publica una
lista de herramientas, cada una con un nombre, una descripción y un esquema JSON
de sus parámetros. El cliente (Claude Desktop, por ejemplo) obtiene esa lista,
se la muestra al modelo, y cuando el modelo decide usar una herramienta el
cliente la invoca con los argumentos que el modelo eligió y le devuelve el
resultado para que lo explique en lenguaje natural.

Mecánicamente, MCP es JSON-RPC 2.0 sobre un transporte. En este proyecto el
transporte es `stdio`: el cliente arranca el servidor como proceso hijo y los
dos intercambian objetos JSON delimitados por salto de línea a través de stdin y
stdout. La sesión empieza con un handshake (`initialize` → respuesta →
`notifications/initialized`) y después el cliente puede llamar `tools/list`,
`tools/call` y `ping`.

## Por qué una flota, y por qué local

Las empresas con flota propia ya tienen GPS en sus unidades y una plataforma de
rastreo; el dato existe y está completo. El problema es el acceso: hoy hay que
navegar dashboards, aplicar filtros y generar reportes, y quien mejor conoce la
operación suele ser quien menos domina la plataforma.

El servidor corre local por diseño y no solo por requisito del curso: las
posiciones de una flota revelan rutas comerciales, clientes y horarios. Con el
servidor en la máquina del operador, hacia el modelo viaja únicamente el
resultado agregado de cada consulta, nunca el histórico de posiciones.

## Requisitos previos

- Python 3.11 o superior
- `git`
- Opcional: una llave de Google Maps (`GOOGLE_MAPS_API_KEY`) para geocodificación
  con Google y para regenerar rutas. Sin ella todo funciona igual.

## Instalación

```bash
git clone https://github.com/FerAHMz/mcp-local-redes.git
cd mcp-local-redes
python3.11 -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Generar la base de datos

No uso datos reales de ninguna empresa. El generador simula 15 vehículos durante
7 días sobre rutas reales del área metropolitana de Guatemala, un reporte cada
15 segundos dentro de la jornada de cada unidad, con ruido GPS de σ ≈ 5 m y
eventos inyectados que conozco de antemano (paradas prolongadas, excesos de
velocidad, pérdidas de señal, entradas y salidas de geocerca).

```bash
python datos/generador.py
```

Produce `datos/flota.db` (SQLite, ~160 000 posiciones y ~1 300 eventos) en un
par de segundos. Por defecto el set termina en el momento en que se corre, así
que "hoy" y "ayer" en las preguntas se refieren a fechas reales. Para un set
reproducible se fija el instante final:

```bash
python datos/generador.py --ahora 2026-08-19T15:30
```

Conviene generarlo en horario laboral (o pasar un `--ahora` con hora laboral)
para que en `unidades_detenidas` haya unidades en ruta y no solo apagadas.

### Rutas: modo offline y modo con API

Las rutas base están guardadas en `datos/rutas/*.json` como polilíneas
codificadas (el mismo formato que devuelve la Directions API de Google), junto
con las paradas de cada una. El generador las lee de ahí y **no necesita red ni
llave**.

Para volver a pedirlas a la Directions API (por ejemplo, para cambiar las paradas
editando los JSON):

```bash
export GOOGLE_MAPS_API_KEY=...
python datos/generador.py --regenerar-rutas
```

## Correr el servidor con el cliente de prueba

El servidor por sí solo no es interactivo: lee JSON de stdin y escribe JSON en
stdout. Para verlo funcionar escribí `cliente_prueba.py`, que lo arranca como
subproceso, hace el handshake, lista las herramientas y permite invocarlas,
imprimiendo cada mensaje tal como viaja en cada dirección.

```bash
python cliente_prueba.py          # interactivo
python cliente_prueba.py --demo   # las seis herramientas y tres casos de error, de corrido
```

En modo interactivo se escribe el número de la herramienta, se responden sus
parámetros y se ve el request, la respuesta y el resultado. También acepta
`ping` y `lista`.

El servidor también se puede probar a mano:

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"ping"}\n' | python -m servidor.main
```

Los logs del servidor van a stderr; con `--verbose` imprime además cada mensaje
que entra y sale.

## Conectarlo a Claude Desktop

Editar el archivo de configuración de Claude Desktop:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

y agregar el servidor con las rutas absolutas del repositorio:

```json
{
  "mcpServers": {
    "flota": {
      "command": "/ruta/absoluta/mcp-local-redes/.venv/bin/python",
      "args": ["/ruta/absoluta/mcp-local-redes/servidor/main.py"]
    }
  }
}
```

En Windows `command` es `C:\\ruta\\mcp-local-redes\\.venv\\Scripts\\python.exe`.
Si se quiere geocodificación con Google se agrega
`"env": {"GOOGLE_MAPS_API_KEY": "..."}` dentro de `"flota"`.

Al reiniciar Claude Desktop aparecen las seis herramientas y se puede preguntar
en lenguaje natural. La base de datos se busca en `datos/flota.db` relativa al
repositorio; se puede cambiar con la variable `MCP_FLOTA_DB`.

## Herramientas

| Herramienta | Pregunta que responde | Parámetros | Devuelve |
|---|---|---|---|
| `posicion_actual` | ¿Dónde está la P-123BCD? | `placa` | Dirección, coordenadas, velocidad, rumbo, estado del motor y hora del último reporte |
| `unidades_detenidas` | ¿Qué unidades llevan más de 30 minutos detenidas? | `minutos_minimos` (opcional, default 30) | Placa, ubicación, desde cuándo y si tiene motor encendido, por unidad |
| `resumen_recorrido` | Dame el recorrido de la P-456DEF de ayer | `placa`, `fecha` | Kilómetros, hora de salida y retorno, paradas (número, duración, las más largas), velocidad máxima y promedio, huecos de señal |
| `alertas` | ¿Hubo excesos de velocidad esta semana? | `tipo` (opcional), `fecha_inicio`, `fecha_fin` | Conteo por tipo y por unidad, y detalle de los eventos más graves |
| `verificar_geocerca` | ¿La P-456DEF entró al CEDIS hoy? | `placa`, `nombre_geocerca`, `fecha` | Si entró, con hora de entrada y salida y minutos dentro por visita |
| `reporte_kilometraje` | ¿Cuál unidad recorrió más kilómetros este mes? | `fecha_inicio`, `fecha_fin` | Ranking de unidades por kilometraje con días operados y promedio diario |

Fechas en formato `AAAA-MM-DD`. Tipos de alerta: `exceso_velocidad`,
`parada_prolongada`, `perdida_senal`, `geocerca_entrada`, `geocerca_salida`.

Geocercas definidas en el set sintético: CEDIS Zona 12, Bodega Villa Nueva,
Bodega Mixco, CD Zona 18, Bodega Carretera a El Salvador y Centro Histórico.
`verificar_geocerca` acepta el nombre completo o una parte ("cedis", "mixco").

**Ninguna herramienta devuelve datos crudos.** Siete días de quince unidades
reportando cada quince segundos son cientos de miles de filas; mandarlas al
modelo es inviable e innecesario. Cada herramienta agrega en SQL o en pandas y
devuelve el resultado calculado. El tope de filas por respuesta es la constante
`MAX_FILAS = 200` en `servidor/registro.py`, y hay una prueba que lo verifica
para cada herramienta.

## Ejemplos de preguntas

- ¿Dónde está la P-123BCD ahorita?
- ¿Hay unidades que lleven más de una hora paradas?
- Dame el resumen del recorrido de la P-456DEF de ayer.
- ¿Cuántas paradas hizo la P-234KLM el lunes y dónde fue la más larga?
- ¿Hubo excesos de velocidad esta semana? ¿Qué unidad tuvo más?
- ¿Qué unidad perdió señal en los últimos siete días?
- ¿La P-456DEF entró al CEDIS ayer? ¿A qué hora y cuánto estuvo?
- ¿Cuál unidad recorrió más kilómetros esta semana?
- ¿Cuántos kilómetros hizo la flota completa del lunes al viernes?

## Pruebas

```bash
python -m pytest tests -v
```

Dos grupos:

- `tests/test_protocolo.py`: handshake correcto, rechazo de métodos antes de
  `initialize`, JSON malformado → `-32700`, request inválido → `-32600`, método
  inexistente → `-32601`, argumentos inválidos → `-32602`, una notificación no
  genera respuesta, el `id` de la respuesta coincide con el del request, una
  respuesta nunca lleva `result` y `error` a la vez, y un arranque real del
  proceso por stdio con cierre limpio en EOF.
- `tests/test_herramientas.py`: cada herramienta contra un set generado en un
  directorio temporal con semilla fija, verificando contra los eventos que el
  generador inyectó a propósito (las unidades que dejé detenidas, las paradas
  prolongadas, los huecos de señal, los excesos de velocidad), los errores de
  negocio, y que ninguna respuesta supera `MAX_FILAS`.

## Implementación del protocolo

Todo lo que toca el protocolo está escrito a mano con `sys`, `json` y `logging`.
`pandas`, `shapely` y `geopy` son lógica de negocio; `requests` solo lo usa el
generador de datos.

- **`servidor/main.py`, transporte.** Lee stdin línea por línea, escribe cada
  respuesta en stdout seguida de `\n` y `flush()`. Todo log va a stderr porque
  stdout es el canal del protocolo y un solo byte de más lo rompe. En EOF cierra
  la base y termina con código 0.
- **`servidor/jsonrpc.py`, JSON-RPC 2.0.** Parsea y valida cada mensaje,
  distingue request de notificación por la presencia de la llave `id` (no por su
  valor, porque `null` es un `id` válido), y arma respuestas y errores con los
  códigos estándar `-32700`, `-32600`, `-32601`, `-32602` y `-32603`.
- **`servidor/protocolo.py`, MCP.** Handshake de inicialización con máquina de
  estados (`NUEVA` → `INICIALIZANDO` → `LISTA`): cualquier método que no sea
  `initialize` o `ping` se rechaza hasta que llega `notifications/initialized`.
  Negociación de versión: si el cliente pide una versión que soporto se la
  devuelvo, si no le devuelvo la más reciente que sí. `tools/list`, `tools/call`
  y `ping`. Las notificaciones que no manejo se ignoran en silencio, porque
  responder a una notificación rompe al cliente.
- **`servidor/registro.py`.** Lista de herramientas con su `inputSchema` y
  validación de argumentos contra él (tipos, `required`, `enum`). Aquí vive
  `MAX_FILAS`.

Decidí separar JSON-RPC de MCP porque son dos niveles distintos del protocolo:
JSON-RPC define la forma de los mensajes y MCP define qué métodos existen y en
qué orden. Separarlos me permitió probar la validación de mensajes sin una
sesión y la máquina de estados sin stdin.

La distinción que más cuidé está en `tools/call`: si la herramienta no existe o
los argumentos no cumplen el esquema, es un error del protocolo y se devuelve
como `error` JSON-RPC con `-32602`; si la herramienta existe y corre pero el
resultado es un fallo de negocio (placa inexistente, día sin datos), se devuelve
como `result` con `isError: true` y un mensaje legible, para que el modelo se lo
pueda explicar al usuario.

La traza completa de una sesión real, con el JSON exacto de cada mensaje, está
en [`docs/protocolo.md`](docs/protocolo.md).

## Estructura del repositorio

```
mcp-local-redes/
├── servidor/
│   ├── main.py              # punto de entrada, bucle de stdio
│   ├── jsonrpc.py           # construcción y validación de mensajes JSON-RPC 2.0
│   ├── protocolo.py         # handshake, máquina de estados, despacho de métodos
│   ├── registro.py          # registro de herramientas, validación de argumentos, MAX_FILAS
│   └── herramientas/
│       ├── comun.py         # consultas compartidas
│       ├── geocodificacion.py
│       ├── posicion.py
│       ├── detenidas.py
│       ├── recorrido.py
│       ├── alertas.py
│       ├── geocercas.py
│       └── kilometraje.py
├── datos/
│   ├── generador.py         # set sintético
│   ├── esquema.sql
│   └── rutas/               # polilíneas guardadas para modo offline
├── cliente_prueba.py
├── tests/
│   ├── test_protocolo.py
│   └── test_herramientas.py
├── docs/
│   └── protocolo.md
└── requirements.txt
```
