# fusion-client

Cliente compartido de **Oracle Fusion Cloud Applications** para Python. Es el
código que antes estaba duplicado byte a byte en cuatro proyectos
(`fusion-data-studio`, `fusion-checklist`, `MQ-Check-pinero` y
`ERP Cloud Dashboard de Cierre`) y que ahora vive en un solo sitio.

Sin dependencias más allá de `requests`. Funciona en Python 3.9 y 3.12.

## La frontera: `bip` sólo lee, `ess` sólo actúa

Es la decisión de diseño central del paquete y **no se debe difuminar**:

| Módulo | Endpoint | Qué hace |
|---|---|---|
| `fusion_client.bip` | `/xmlpserver/services/ExternalReportWSSService` (BI Publisher, SOAP 1.2) | **Sólo LEE.** Ejecuta data models / reports y devuelve los datos. |
| `fusion_client.ess` | `/fscmService/ErpIntegrationService` (ERP Integration, SOAP 1.1) | **Sólo ACTÚA.** Envía procesos programados (ESS jobs) y consulta su estado. |

Una lectura nunca debe poder disparar un job, y un job nunca debe devolverse
como si fuera el resultado de una consulta. Por eso son dos módulos y no uno:
la separación es lo que permite auditar de un vistazo qué parte de una
aplicación puede escribir en Fusion.

Oracle Fusion SaaS no expone la base de datos (no hay JDBC). La vía soportada
para "ejecutar SQL" es crear un Data Model en BI Publisher con la SQL, ponerle
un report encima y lanzarlo — que es justo lo que hace `bip.run_sql`.

## Instalación

El paquete no está en PyPI; se instala desde el repositorio:

```bash
pip install "fusion-client @ git+https://github.com/jrubioadies/fusion-client.git"
```

En los proyectos consumidores esa misma línea está en su `requirements.txt`,
así que basta con:

```bash
pip install -r requirements.txt
```

Para desarrollar sobre el propio paquete:

```bash
git clone https://github.com/jrubioadies/fusion-client.git
cd fusion-client
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Uso

```python
from fusion_client import bip, ess
from fusion_client.errors import FusionAuthError, FusionSQLError

# LEER: ejecutar SQL vía el report ejecutor
datos = bip.run_sql(base, user, pw, "/Custom/SQLTools/SQLConReport.xdo",
                    "select 1 from dual")
columnas, filas = bip.parse_rows(datos)

# ACTUAR: lanzar un ESS job y esperar
rid = ess.submit_ess_job(base, user, pw, job_package, job_definition, ["Jul-26"])
estado = ess.get_job_status(base, user, pw, rid)
ess.classify_status(estado)   # 'ok' | 'warn' | 'error' | 'running'
```

También trae un CLI, `fbip` (`fbip test`, `ls`, `params`, `run`, `sql`,
`setup`, `save-creds`).

## Errores

Todo lo que lanza la librería cuelga de `FusionError`, y **`FusionError`
hereda de `RuntimeError`**. Eso es deliberado: los proyectos consumidores
tienen 15 puntos que capturan `except (RuntimeError, SystemExit)`, y siguen
funcionando sin tocarlos. Quien quiera distinguir el caso concreto, puede.

```
RuntimeError
└── FusionError
    ├── FusionAuthError      401 — credenciales o permisos (bip y ess)
    ├── FusionSQLError       ORA-xxxxx / java.sql.* devuelto por la BD
    ├── FusionTooLongError   la SQL pasa de los 192 KB del data model
    ├── FusionBIPError       fallo de BI Publisher que no es auth ni SQL
    └── FusionESSError       fallo del ERP Integration Service
```

La librería **nunca llama a `sys.exit`**: sólo lo hace el CLI (`bip.main`).
Un módulo que mata el proceso no se puede reutilizar.

## Tests

```bash
.venv/bin/python -m pytest -q
```

**Ningún test toca la red.** `bip` se prueba con `monkeypatch` sobre
`requests.post`; `ess` tiene el transporte HTTP inyectable (`transport=`), una
función `(url, body, user, pw, timeout) -> (status_code, text)`.

Los tests marcados `@pytest.mark.live` sí irían contra una instancia real y
están **desactivados por defecto** (`addopts = "-m 'not live'"` en
`pyproject.toml`).
