"""Authentication router - login & token generation."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.user import User
from backend.security import verify_password, create_access_token
from backend.schemas.schemas import LoginRequest, TokenResponse, UserRead

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.email == form.username,
        User.is_deleted == False,
    ).first()

    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Usuario desactivado")

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TokenResponse(
        access_token=token,
        user=UserRead.model_validate(user),
    )
