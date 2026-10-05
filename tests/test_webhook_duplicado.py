"""Un reintento del webhook de YCloud no puede generar otra respuesta."""
from backend.routers import evolution_router as er


def test_el_mismo_mensaje_se_procesa_una_sola_vez(monkeypatch):
    monkeypatch.setattr(er, "_mensajes_vistos", {})
    assert er.ya_procesado("wamid.ABC") is False
    assert er.ya_procesado("wamid.ABC") is True
    assert er.ya_procesado("wamid.XYZ") is False


def test_sin_id_no_se_descarta(monkeypatch):
    monkeypatch.setattr(er, "_mensajes_vistos", {})
    assert er.ya_procesado(None) is False
    assert er.ya_procesado(None) is False


def test_pasada_la_ventana_se_olvida(monkeypatch):
    monkeypatch.setattr(er, "_mensajes_vistos", {"wamid.VIEJO": -10_000.0})
    assert er.ya_procesado("wamid.VIEJO") is False
