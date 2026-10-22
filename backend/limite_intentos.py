"""Límite de intentos fallidos (login), en memoria.

El login no tenía ningún límite: se podía probar contraseñas sin parar, y las
de ejemplo (admin123) estuvieron públicas en el repo. Producción corre en un
solo proceso, así que la memoria alcanza; si algún día hay varios workers,
cada uno lleva su cuenta (el límite efectivo se multiplica, no se rompe).
"""
import threading
import time
from collections import defaultdict, deque


class Limitador:
    def __init__(self, maximo: int, ventana_segundos: int):
        self.maximo = maximo
        self.ventana = ventana_segundos
        self._fallos: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _purgar(self, clave: str, ahora: float):
        cola = self._fallos.get(clave)
        while cola and ahora - cola[0] > self.ventana:
            cola.popleft()
        if cola is not None and not cola:
            del self._fallos[clave]

    def espera(self, clave: str) -> int:
        """Segundos que faltan para poder volver a intentar (0 = puede)."""
        ahora = time.monotonic()
        with self._lock:
            self._purgar(clave, ahora)
            cola = self._fallos.get(clave)
            if not cola or len(cola) < self.maximo:
                return 0
            return max(1, int(self.ventana - (ahora - cola[0])) + 1)

    def fallo(self, clave: str):
        ahora = time.monotonic()
        with self._lock:
            self._purgar(clave, ahora)
            self._fallos[clave].append(ahora)

    def limpiar(self, clave: str):
        with self._lock:
            self._fallos.pop(clave, None)


def ip_del_cliente(request) -> str:
    """La IP real detrás de Cloudflare y Traefik.

    Las cabeceras se pueden falsificar si alguien le pega directo al VPS sin
    pasar por Cloudflare: por eso el límite por cuenta no depende de la IP.
    """
    h = request.headers
    ip = h.get("cf-connecting-ip") or (h.get("x-forwarded-for") or "").split(",")[0].strip()
    return ip or (request.client.host if request.client else "?")
