"""La hora de la clínica sale del reloj del sistema + zona horaria, sin HTTP.

Antes se consultaba worldtimeapi.org en cada mensaje (timeout 3s, caché 10').
Si fallaba, caía a UTC-3 fijo; si tardaba, el paciente esperaba. La zona
horaria de Argentina no tiene horario de verano: `zoneinfo` alcanza.
"""
from datetime import datetime, timezone

from backend.services import appointment_service as svc


def test_no_hace_http_para_saber_la_hora(monkeypatch):
    def _explota(*a, **k):
        raise AssertionError("get_clinic_now no puede salir a la red")
    monkeypatch.setattr(svc.httpx, "get", _explota)

    assert isinstance(svc.get_clinic_now(), datetime)


def test_es_utc_menos_3():
    ahora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    clinica = svc.get_clinic_now()
    diff_h = round((ahora_utc - clinica).total_seconds() / 3600)
    assert diff_h == 3, f"Argentina es UTC-3, dio UTC{-diff_h:+d}"


def test_es_naive_como_el_resto_del_sistema():
    """Todo el backend compara con datetimes sin tzinfo."""
    assert svc.get_clinic_now().tzinfo is None
