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
