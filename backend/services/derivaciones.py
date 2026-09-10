"""Casos que esperan a una persona de la clinica.

Pausar el bot no es avisarle a nadie. Antes el bot decia "dejé la consulta para
que la revisen" y lo unico que ocurria era que se callaba: recepcion no tenia
donde enterarse. Ahora la afirmacion solo se puede hacer si la fila existe.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.models.derivacion import (
    Derivacion, EstadoDerivacion, MotivoDerivacion,
)

logger = logging.getLogger(__name__)

# Dos mensajes seguidos sobre lo mismo no son dos casos para recepcion.
VENTANA_ANTI_REPETIDO = timedelta(hours=6)


def crear_derivacion(db: Session, remote_jid: str, motivo: MotivoDerivacion,
                     resumen: str, datos_aportados: str | None = None,
                     telefono: str | None = None) -> Derivacion | None:
    """Deja el caso para recepcion. Devuelve None si no se pudo crear.

    Quien llama TIENE que mirar el resultado: decirle al paciente "ya avisé"
    cuando esto devolvio None es exactamente la promesa vacia que hay que
    evitar.
    """
    try:
        repetida = db.query(Derivacion).filter(
            Derivacion.remote_jid == remote_jid,
            Derivacion.motivo == motivo,
            Derivacion.estado == EstadoDerivacion.pendiente,
            Derivacion.is_deleted == False,  # noqa: E712
            Derivacion.created_at >= datetime.utcnow() - VENTANA_ANTI_REPETIDO,
        ).first()
        if repetida:
            # Se actualiza con lo ultimo que dijo, en vez de apilar casos.
            if datos_aportados:
                repetida.datos_aportados = datos_aportados
            repetida.resumen = resumen or repetida.resumen
            db.commit()
            return repetida

        d = Derivacion(
            remote_jid=remote_jid,
            telefono=telefono or "".join(filter(str.isdigit, (remote_jid or "").split("@")[0])),
            motivo=motivo,
            resumen=(resumen or "").strip()[:2000],
            datos_aportados=(datos_aportados or None),
        )
        db.add(d)
        db.commit()
        db.refresh(d)
        logger.info("📋 Derivación creada (%s) para %s", motivo.value, d.telefono[-4:] if d.telefono else "?")
        return d
    except Exception as e:
        db.rollback()
        logger.error("❌ No se pudo crear la derivación: %s", e, exc_info=True)
        return None


def pendientes(db: Session) -> list[Derivacion]:
    return db.query(Derivacion).filter(
        Derivacion.estado == EstadoDerivacion.pendiente,
        Derivacion.is_deleted == False,  # noqa: E712
    ).order_by(Derivacion.created_at.desc()).all()


def hay_pendiente(db: Session, remote_jid: str) -> bool:
    """Si esta conversacion tiene algo sin resolver.

    Se usa para no reactivar el bot solo porque vencio el temporizador: si
    quedo una tarea humana abierta, reanudar la admision seria contradecir a
    quien todavia no pudo atenderla.
    """
    return db.query(Derivacion).filter(
        Derivacion.remote_jid == remote_jid,
        Derivacion.estado == EstadoDerivacion.pendiente,
        Derivacion.is_deleted == False,  # noqa: E712
    ).first() is not None


def resolver(db: Session, derivacion_id, por: str | None = None,
             nota: str | None = None) -> Derivacion | None:
    d = db.query(Derivacion).filter(Derivacion.id == derivacion_id).first()
    if not d:
        return None
    d.estado = EstadoDerivacion.resuelta
    d.resuelta_at = datetime.utcnow()
    d.resuelta_por = por
    d.nota_de_cierre = nota
    db.commit()
    db.refresh(d)
    return d
