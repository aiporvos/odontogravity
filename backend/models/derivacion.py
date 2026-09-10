import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class MotivoDerivacion(str, enum.Enum):
    """Por que esta conversacion necesita a una persona."""
    identidad = "identidad"            # no se pudo verificar quien escribe
    pedido_de_persona = "pedido_de_persona"
    clinico = "clinico"                # dolor, protesis que lastima, urgencia
    dato_faltante = "dato_faltante"    # precio/alias que no esta en el catalogo
    otro = "otro"


class EstadoDerivacion(str, enum.Enum):
    pendiente = "pendiente"
    resuelta = "resuelta"


class Derivacion(Base):
    """Una conversacion que espera a recepcion, con lo que el paciente ya dijo.

    Existe porque pausar el bot no es avisarle a nadie. El bot decia "dejé la
    consulta para que la revisen" y lo unico que pasaba era que se callaba: no
    habia ningun lado donde recepcion pudiera ver que alguien la estaba
    esperando. Una paciente pidio cancelar su turno del dia siguiente, el bot no
    pudo identificarla —su ficha venia de la agenda de papel, sin DNI ni
    telefono— y la conversacion termino en "¿podrias darme el nombre y apellido
    de otra persona?". Nadie se entero.

    Con esto, el bot solo puede afirmar que dejo la consulta si la fila existe.
    """
    __tablename__ = "derivaciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    remote_jid: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    telefono: Mapped[str | None] = mapped_column(String(30), nullable=True)

    motivo: Mapped[MotivoDerivacion] = mapped_column(
        SAEnum(MotivoDerivacion), nullable=False, default=MotivoDerivacion.otro)
    # Lo que el paciente pidio, en sus palabras. Recepcion no tiene que leer
    # toda la conversacion para saber de que se trata.
    resumen: Mapped[str] = mapped_column(Text, nullable=False)
    # Los datos que aporto y no se pudieron verificar (nombre, DNI, fecha del
    # turno que dice tener). Se conservan para que no tenga que repetirlos.
    datos_aportados: Mapped[str | None] = mapped_column(Text, nullable=True)

    estado: Mapped[EstadoDerivacion] = mapped_column(
        SAEnum(EstadoDerivacion), nullable=False, default=EstadoDerivacion.pendiente, index=True)
    resuelta_por: Mapped[str | None] = mapped_column(String(120), nullable=True)
    nota_de_cierre: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    resuelta_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
