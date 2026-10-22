"""Que los logs no guarden teléfonos ni DNI de pacientes.

Los logs del contenedor escribían el número completo de cada paciente junto con
lo que decía: información de salud identificable en un lugar que no tiene
control de acceso ni vencimiento. Se tapa en un solo lugar, para todo log que
se escriba (también los que se agreguen después): de cualquier número de 7 o
más dígitos quedan los 3 últimos, que alcanzan para seguir un caso.

Las fechas (2026-10-22) y las horas no se tocan.
"""
import logging
import re

# 7+ dígitos seguidos (DNI, teléfono, +549...), o característica + número
# ("2604-590071", "260 4590071").
_NUMERO = re.compile(r"\+?(?<![\d-])(?:\d{7,}|\d{2,5}[\s-]\d{6,8})(?![\d-])")


def tapar_numeros(texto: str) -> str:
    def _tapar(m):
        digitos = re.sub(r"\D", "", m.group(0))
        return "…" + digitos[-3:]
    return _NUMERO.sub(_tapar, texto)


def instalar():
    """Envuelve la fábrica de registros: aplica a todos los loggers y handlers."""
    anterior = logging.getLogRecordFactory()
    if getattr(anterior, "_tapa_numeros", False):
        return

    def fabrica(*args, **kwargs):
        record = anterior(*args, **kwargs)
        try:
            mensaje = record.getMessage()
        except Exception:
            return record
        tapado = tapar_numeros(mensaje)
        if tapado != mensaje:
            record.msg, record.args = tapado, None
        return record

    fabrica._tapa_numeros = True
    logging.setLogRecordFactory(fabrica)
