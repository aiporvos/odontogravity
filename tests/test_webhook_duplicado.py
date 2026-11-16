"""Un reintento del webhook de YCloud no puede generar otra respuesta."""
from sqlalchemy import text

from backend.routers import whatsapp_router as er


def test_el_mismo_mensaje_se_procesa_una_sola_vez(db):
    assert er.ya_procesado("wamid.ABC") is False
    assert er.ya_procesado("wamid.ABC") is True
    assert er.ya_procesado("wamid.XYZ") is False


def test_sobrevive_a_un_reinicio(db):
    """Vive en la base: un proceso nuevo (o un reinicio) lo sigue viendo."""
    assert er.ya_procesado("wamid.REINICIO") is False
    count = db.execute(text("SELECT count(*) FROM mensajes_procesados WHERE wamid = 'wamid.REINICIO'")).scalar()
    assert count == 1
    assert er.ya_procesado("wamid.REINICIO") is True


def test_sin_id_no_se_descarta(db):
    assert er.ya_procesado(None) is False
    assert er.ya_procesado(None) is False


def test_pasados_dos_dias_se_olvida(db):
    db.execute(text("INSERT INTO mensajes_procesados (wamid, recibido) "
                    "VALUES ('wamid.VIEJO', now() - interval '3 days')"))
    db.commit()
    assert er.ya_procesado("wamid.VIEJO") is False


def test_si_la_base_falla_se_procesa(monkeypatch):
    """Ante la duda, procesar: perder un mensaje del paciente es peor."""
    class _Rota:
        def execute(self, *a, **k): raise RuntimeError("base caida")
        def rollback(self): pass
        def close(self): pass
    monkeypatch.setattr(er, "SessionLocal", lambda: _Rota())
    assert er.ya_procesado("wamid.CUALQUIERA") is False
