"""El modelo se elige desde un desplegable del panel: el bot tiene que mandar
los parámetros que cada familia acepta, o la llamada a la IA falla con 400."""
import pytest

from bot.ai_agent import _parametros_modelo


@pytest.mark.parametrize("modelo", ["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.5", "openai/gpt-5.4-mini", "o4-mini"])
def test_gpt5_y_o_series_usan_max_completion_tokens(modelo):
    p = _parametros_modelo(modelo)
    assert "temperature" not in p and "max_tokens" not in p
    assert p["max_completion_tokens"] >= 1000


@pytest.mark.parametrize("modelo", ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "google/gemini-flash-1.5", "", None])
def test_los_demas_siguen_con_temperature_y_max_tokens(modelo):
    assert _parametros_modelo(modelo) == {"temperature": 0.3, "max_tokens": 1000}
