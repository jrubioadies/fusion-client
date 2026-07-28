"""Errores del cliente de Fusion.

Existen para que la librería nunca tenga que llamar a sys.exit. Un módulo
que mata el proceso no se puede reutilizar: obliga a quien lo importa a
capturar SystemExit, que es exactamente lo que pasaba antes de esto.
"""


class FusionError(RuntimeError):
    """Base de todos los errores del cliente.

    Hereda de RuntimeError, no de Exception, y es deliberado: los cuatro
    proyectos consumidores tienen 15 puntos que capturan
    `except (RuntimeError, SystemExit)`, y `main()` captura `except
    RuntimeError`. Con Exception como base, cada 401 y cada error de SQL se
    escaparía de los 15 sitios y saldría por traza. Heredar de RuntimeError
    mantiene ese contrato intacto y permite además distinguir el caso
    concreto capturando FusionAuthError.
    """


class FusionAuthError(FusionError):
    """Credenciales inválidas o sin permiso (HTTP 401/403)."""


class FusionSQLError(FusionError):
    """Error devuelto por la base de datos (ORA-xxxxx, java.sql.*)."""


class FusionTooLongError(FusionError):
    """La consulta supera el tope que admite el data model (192 KB)."""


class FusionBIPError(FusionError):
    """Fallo del lado de BI Publisher que no es ni auth ni SQL.

    Cubre dos casos: un HTTP >= 400 cuyo fault no contiene ORA-/java.sql, y
    una respuesta HTTP 200 cuyo cuerpo no trae `reportBytes`. El segundo está
    en la ruta que usan los cuatro consumidores (`run_sql`), así que conviene
    poder distinguirlo de un error de red o de credenciales.
    """


class FusionESSError(FusionError):
    """Fallo del lado del ERP Integration Service (envío/consulta de jobs).

    `ess` es el único módulo que ESCRIBE en Fusion. Que sus fallos tengan tipo
    propio es lo que permite a quien lo llama decidir si reintenta, si aborta
    la secuencia de cierre o si sólo avisa. Los 401 NO llegan aquí: usan
    FusionAuthError, igual que en `bip`, para que un mismo `except` sirva para
    las credenciales de los dos módulos.
    """
