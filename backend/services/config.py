"""Configuracion: un solo lugar para leerla.

Habia cinco copias de get_config y todas leian primero la tabla app_configs y
despues el entorno. Con las claves eso fue un problema serio: se veian desde el
panel, se podian pisar desde ahi y rotarlas en Dokploy no alcanzaba porque la
base tenia prioridad.

La regla ahora:
- Secretos (*_API_KEY, *_TOKEN, *_SECRET): SOLO del entorno (Dokploy).
- Lo operativo del consultorio (modelo, pausa del bot, numeros de aviso,
  sillones, demoras): de app_configs, que se edita desde el panel, y si no
  esta ahi, del entorno.
"""
import logging
import os

from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models.config import AppConfig

logger = logging.getLogger(__name__)

SUFIJOS_SECRETOS = ("_API_KEY", "_TOKEN", "_SECRET")


def es_secreto(key: str) -> bool:
    return key.endswith(SUFIJOS_SECRETOS)


def _limpio(valor):
    # .strip() a proposito: una clave o un numero pegado desde otra pantalla
    # arrastra espacios o un salto de linea, y el 401 que devuelve despues no da
    # ninguna pista de que sobra un caracter invisible.
    return valor.strip() if isinstance(valor, str) else valor


def get_config(key: str, default: str = "", db: Session | None = None) -> str:
    if es_secreto(key):
        return _limpio(os.getenv(key, default))

    propia = db is None
    if propia:
        db = SessionLocal()
    try:
        conf = db.query(AppConfig).filter(AppConfig.key == key).first()
        if conf and conf.value and conf.value.strip():
            return conf.value.strip()
    except Exception as e:
        logger.warning("No se pudo leer '%s' de app_configs: %s", key, e)
    finally:
        if propia:
            db.close()
    return _limpio(os.getenv(key, default))
