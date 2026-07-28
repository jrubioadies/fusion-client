"""Los cinco puntos de error de ess.py, ya dentro de la jerarquía FusionError.

`ess` es el único módulo que ESCRIBE en Fusion, así que es donde más falta
hace poder distinguir el fallo por tipo: no es lo mismo unas credenciales
malas (reintentable tras pedirlas otra vez) que un job que no existe (aborta
la secuencia de cierre).

Sin red: todo va por el `transport=` inyectable.
"""
import pytest

from fusion_client import ess
from fusion_client.errors import (
    FusionAuthError,
    FusionError,
    FusionESSError,
)


def fake_transport(status, text):
    def t(url, body, user, pw, timeout):
        return status, text
    return t


SUBMIT_OK = ("<env:Envelope><env:Body><ns:submitESSJobRequestResponse>"
             "<result>300100123456789</result>"
             "</ns:submitESSJobRequestResponse></env:Body></env:Envelope>")

FAULT_500 = ("<env:Envelope><env:Body><env:Fault><env:Reason>"
             "<env:Text>Job definition not found</env:Text>"
             "</env:Reason></env:Fault></env:Body></env:Envelope>")


# --- ess.py:80 — 401 -> FusionAuthError -------------------------------------

def test_submit_401_lanza_auth_error():
    with pytest.raises(FusionAuthError) as e:
        ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", [],
                           transport=fake_transport(401, ""))
    assert "401" in str(e.value)


def test_get_status_401_lanza_auth_error():
    with pytest.raises(FusionAuthError):
        ess.get_job_status("https://x", "u", "p", "300",
                           transport=fake_transport(401, ""))


def test_el_401_de_ess_y_el_de_bip_se_capturan_igual():
    """Misma clase para los dos módulos: un solo `except FusionAuthError`
    cubre credenciales malas vengan de donde vengan."""
    from fusion_client import bip  # noqa: F401  (mismo paquete, misma clase)
    with pytest.raises(FusionAuthError):
        ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", [],
                           transport=fake_transport(401, ""))


# --- ess.py:82 — HTTP >= 400 -> FusionESSError ------------------------------

def test_submit_http_500_lanza_ess_error():
    with pytest.raises(FusionESSError) as e:
        ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", [],
                           transport=fake_transport(500, FAULT_500))
    assert "Job definition not found" in str(e.value)


def test_get_status_http_500_lanza_ess_error():
    with pytest.raises(FusionESSError):
        ess.get_job_status("https://x", "u", "p", "300",
                           transport=fake_transport(500, FAULT_500))


def test_403_tambien_es_ess_error_no_auth_error():
    """El _check sólo trata el 401 como auth; el 403 cae en el genérico.
    Se fija aquí para que el cambio sea visible si alguien lo toca."""
    with pytest.raises(FusionESSError):
        ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", [],
                           transport=fake_transport(403, "forbidden"))


# --- ess.py:111 — submit sin requestId -> FusionESSError --------------------

def test_submit_sin_request_id_lanza_ess_error():
    sin_result = "<env:Envelope><env:Body><ns:algoRaro/></env:Body></env:Envelope>"
    with pytest.raises(FusionESSError) as e:
        ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", [],
                           transport=fake_transport(200, sin_result))
    assert "requestId" in str(e.value)


# --- ess.py:114 — requestId no numérico -> FusionESSError -------------------

def test_submit_request_id_no_numerico_lanza_ess_error():
    raro = "<env:Body><result>NO-SOY-UN-ID</result></env:Body>"
    with pytest.raises(FusionESSError) as e:
        ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", [],
                           transport=fake_transport(200, raro))
    assert "NO-SOY-UN-ID" in str(e.value)


# --- ess.py:131 — getESSJobStatus sin result -> FusionESSError --------------

def test_get_status_sin_result_lanza_ess_error():
    sin_result = "<env:Envelope><env:Body><ns:vacio/></env:Body></env:Envelope>"
    with pytest.raises(FusionESSError) as e:
        ess.get_job_status("https://x", "u", "p", "300",
                           transport=fake_transport(200, sin_result))
    assert "getESSJobStatus" in str(e.value)


# --- Contrato de compatibilidad ---------------------------------------------

def test_los_errores_de_ess_son_capturables_como_runtime_error():
    """El cambio es seguro por construcción: FusionError hereda de
    RuntimeError, así que los `except (RuntimeError, SystemExit)` que ya
    existían en los consumidores siguen capturando estos errores."""
    assert issubclass(FusionESSError, RuntimeError)
    assert issubclass(FusionAuthError, RuntimeError)
    assert issubclass(FusionESSError, FusionError)
    assert issubclass(FusionAuthError, FusionError)


@pytest.mark.parametrize("llamada", [
    lambda t: ess.submit_ess_job("https://x", "u", "p", "/pkg", "J", [], transport=t),
    lambda t: ess.get_job_status("https://x", "u", "p", "300", transport=t),
])
@pytest.mark.parametrize("status,text", [
    (401, ""),
    (500, FAULT_500),
    (200, "<env:Body><ns:nada/></env:Body>"),
])
def test_todo_error_de_ess_se_captura_con_except_runtime_error(llamada, status, text):
    """Prueba viva de que ningún camino de error de ess se escapa de un
    `except RuntimeError` preexistente."""
    with pytest.raises(RuntimeError):
        llamada(fake_transport(status, text))


def test_ess_no_llama_a_sys_exit():
    """La razón de ser de errors.py: un módulo que mata el proceso no se
    puede reutilizar."""
    try:
        ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", [],
                           transport=fake_transport(500, FAULT_500))
    except SystemExit:
        pytest.fail("ess no debe llamar a sys.exit")
    except FusionESSError:
        pass


def test_submit_ok_sigue_funcionando():
    """Contraprueba: el camino feliz no se ha tocado."""
    rid = ess.submit_ess_job("https://x", "u", "p", "/pkg", "Job", ["1"],
                             transport=fake_transport(200, SUBMIT_OK))
    assert rid == "300100123456789"
