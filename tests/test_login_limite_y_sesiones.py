"""Login con límite de intentos, y sesiones que se cortan al cambiar la contraseña.

Antes se podía probar contraseñas sin límite (y admin123 estuvo pública en el
repo), y un token robado seguía sirviendo 8 h aunque se cambiara la contraseña.
"""
import pytest
from fastapi.testclient import TestClient

from backend.models.user import User, UserRole
from backend.routers import auth
from backend.security import hash_password

CLAVE = "clave-correcta-de-prueba"


@pytest.fixture
def cliente(db):
    for lim in (auth.fallos_por_cuenta, auth.fallos_por_ip):
        lim._fallos.clear()
    db.add_all([
        User(email="recepcion@prueba.com", full_name="Recepción", role=UserRole.receptionist,
             hashed_password=hash_password(CLAVE), is_active=True),
        User(email="admin@prueba.com", full_name="Admin", role=UserRole.admin,
             hashed_password=hash_password(CLAVE), is_active=True),
    ])
    db.commit()
    from backend.main import app
    with TestClient(app) as c:
        yield c


def _login(c, email, clave, ip="200.1.1.1"):
    return c.post("/api/auth/login", data={"username": email, "password": clave},
                  headers={"CF-Connecting-IP": ip})


def test_bloquea_la_cuenta_tras_varios_fallos(cliente):
    for _ in range(auth.fallos_por_cuenta.maximo):
        assert _login(cliente, "recepcion@prueba.com", "mal").status_code == 401
    r = _login(cliente, "recepcion@prueba.com", CLAVE)
    assert r.status_code == 429, "Bloqueado es bloqueado, aunque acierte"
    assert int(r.headers["Retry-After"]) > 0


def test_no_afecta_a_otra_cuenta(cliente):
    for _ in range(auth.fallos_por_cuenta.maximo):
        _login(cliente, "recepcion@prueba.com", "mal")
    assert _login(cliente, "admin@prueba.com", CLAVE).status_code == 200


def test_un_acierto_limpia_los_fallos_de_la_cuenta(cliente):
    for _ in range(auth.fallos_por_cuenta.maximo - 1):
        _login(cliente, "recepcion@prueba.com", "mal")
    assert _login(cliente, "recepcion@prueba.com", CLAVE).status_code == 200
    assert _login(cliente, "recepcion@prueba.com", "mal").status_code == 401


def test_bloquea_la_ip_que_prueba_muchas_cuentas(cliente):
    for i in range(auth.fallos_por_ip.maximo):
        _login(cliente, f"usuario{i}@prueba.com", "mal", ip="9.9.9.9")
    assert _login(cliente, "admin@prueba.com", CLAVE, ip="9.9.9.9").status_code == 429
    assert _login(cliente, "admin@prueba.com", CLAVE, ip="8.8.8.8").status_code == 200


def test_cambiar_la_contrasena_corta_las_sesiones(cliente, db):
    token = _login(cliente, "admin@prueba.com", CLAVE).json()["access_token"]
    cabecera = {"Authorization": f"Bearer {token}"}
    assert cliente.get("/api/admin/configs", headers=cabecera).status_code == 200

    u = db.query(User).filter(User.email == "admin@prueba.com").first()
    u.hashed_password = hash_password("otra-clave-nueva")
    db.commit()

    assert cliente.get("/api/admin/configs", headers=cabecera).status_code == 401


def test_un_token_sin_huella_no_vale(cliente, db):
    from backend.security import create_access_token
    u = db.query(User).filter(User.email == "admin@prueba.com").first()
    viejo = create_access_token({"sub": str(u.id), "role": "admin"})
    r = cliente.get("/api/admin/configs", headers={"Authorization": f"Bearer {viejo}"})
    assert r.status_code == 401
