"""Authentication router - login & token generation."""
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.limite_intentos import Limitador, ip_del_cliente
from backend.models.user import User
from backend.security import verify_password, create_access_token, huella_password
from backend.schemas.schemas import LoginRequest, TokenResponse, UserRead

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])

VENTANA_LOGIN = int(os.getenv("LOGIN_VENTANA_SEGUNDOS", "900"))
# Por cuenta frena a quien prueba contraseñas contra un usuario; por IP, a quien
# prueba muchos usuarios. El de cuenta es más bajo, pero no tanto como para que
# un tercero pueda dejar afuera a recepción con unos pocos intentos.
fallos_por_cuenta = Limitador(int(os.getenv("LOGIN_MAX_POR_CUENTA", "8")), VENTANA_LOGIN)
fallos_por_ip = Limitador(int(os.getenv("LOGIN_MAX_POR_IP", "30")), VENTANA_LOGIN)


@router.post("/login", response_model=TokenResponse)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(),
          db: Session = Depends(get_db)):
    email = form.username.strip().lower()
    cuenta, ip = f"cuenta:{email}", f"ip:{ip_del_cliente(request)}"

    # Antes de mirar la contraseña: bloqueado es bloqueado, aunque acierte.
    espera = max(fallos_por_cuenta.espera(cuenta), fallos_por_ip.espera(ip))
    if espera:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos. Probá de nuevo en {max(1, espera // 60)} minutos.",
            headers={"Retry-After": str(espera)},
        )

    # Comparamos en minusculas: el usuario no tiene por que recordar como estaba
    # escrito el email cuando se dio de alta (y hay registros viejos con mayusculas).
    user = db.query(User).filter(
        func.lower(User.email) == email,
        User.is_deleted == False,
    ).first()

    if not user or not verify_password(form.password, user.hashed_password):
        fallos_por_cuenta.fallo(cuenta)
        fallos_por_ip.fallo(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Usuario desactivado")

    fallos_por_cuenta.limpiar(cuenta)
    token = create_access_token({"sub": str(user.id), "role": user.role.value,
                                 "pwh": huella_password(user)})
    return TokenResponse(
        access_token=token,
        user=UserRead.model_validate(user),
    )
