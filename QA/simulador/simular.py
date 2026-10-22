"""Simulador de pacientes contra OdoBot completo, con IA real.

Levanta el backend de verdad (FastAPI + bot) en esta máquina, sobre una base
descartable con la configuración de producción y SIN pacientes reales. Los
pacientes son otra IA con una personalidad y un objetivo; le escriben al bot
por el webhook firmado, igual que YCloud. Lo que el bot "manda" a WhatsApp se
intercepta: no sale nada. La única salida permitida es OpenRouter.

Uso (la clave entra por el entorno, nunca por argumento):

    SIM_OPENROUTER_KEY=... .venv/bin/python QA/simulador/simular.py \
        --config ruta/config-produccion.json --personas ruta/personas.json \
        --salida ruta/resultados [--solo 01-extraccion-directa,02-...]
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
import uuid
from datetime import datetime, timedelta, time as dtime

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

URL_BASE_SIM = os.getenv(
    "SIM_DATABASE_URL",
    "postgresql://dentibot:dentibot_secure_2024@localhost:5432/dentibot_sim_test",
)
SECRETO_WEBHOOK = secrets.token_hex(16)
NUMERO_BOT = "5492604590071"
NUMERO_AVISOS = "5492600000000"   # ADMIN_NOTIFY_NUMBERS falso
PUERTO = 8765
PROVEEDOR = os.getenv("SIM_PROVEEDOR", "openai")          # openai | openrouter
if PROVEEDOR == "openai":
    CLAVE = os.environ.get("SIM_OPENAI_KEY", "").strip()
    URL_IA = "https://api.openai.com/v1"
    MODELO_BOT = os.getenv("SIM_MODELO_BOT", "gpt-4o-mini")            # = producción
    MODELO_PACIENTE = os.getenv("SIM_MODELO_PACIENTE", "gpt-4o-mini")
    MODELO_JUEZ = os.getenv("SIM_MODELO_JUEZ", "gpt-4.1-mini")
else:
    CLAVE = os.environ.get("SIM_OPENROUTER_KEY", "").strip()
    URL_IA = "https://openrouter.ai/api/v1"
    MODELO_BOT = os.getenv("SIM_MODELO_BOT", "openai/gpt-4o-mini")
    MODELO_PACIENTE = os.getenv("SIM_MODELO_PACIENTE", "google/gemini-2.5-flash")
    MODELO_JUEZ = os.getenv("SIM_MODELO_JUEZ", "anthropic/claude-haiku-4.5")
TOPE_USD = float(os.getenv("SIM_TOPE_USD", "1.5"))

if not CLAVE:
    sys.exit(f"Falta la clave de {PROVEEDOR} en el entorno.")
if "test" not in URL_BASE_SIM.rsplit("/", 1)[-1]:
    sys.exit("La base de simulación tiene que llamarse con 'test': se borra entera.")

# Antes de importar el backend: database.py y security.py leen esto al cargar.
os.environ.update(
    DATABASE_URL=URL_BASE_SIM,
    SECRET_KEY=secrets.token_hex(32),
    BOT_API_KEY=secrets.token_hex(24),
    YCLOUD_WEBHOOK_SECRET=SECRETO_WEBHOOK,
    YCLOUD_WEBHOOK_ENFORCE="true",
    YCLOUD_API_KEY="clave-falsa-simulador",
    YCLOUD_FROM_PHONE=NUMERO_BOT,
    OPENAI_API_KEY="",
    ALLOWED_ORIGINS="http://localhost",
    API_BASE_URL=f"http://127.0.0.1:{PUERTO}",
    PUBLIC_APP_URL="https://odobot.cluna.ar",
)

import httpx  # noqa: E402

# ── Salidas: YCloud interceptado, OpenRouter real, todo lo demás bloqueado ──
ENVIADOS: dict[str, list[dict]] = {}
PERMITIDOS = {"127.0.0.1", "localhost", "openrouter.ai", "api.openai.com"}

# USD por millón de tokens (entrada, entrada cacheada, salida). Precios de lista.
PRECIOS = {"gpt-4o-mini": (0.15, 0.075, 0.60), "gpt-4.1-mini": (0.40, 0.10, 1.60),
           "gpt-4.1-nano": (0.10, 0.025, 0.40), "gpt-5.4-mini": (0.75, 0.075, 4.50),
           "gpt-5.4-nano": (0.20, 0.02, 1.25)}
HERRAMIENTAS: list[dict] = []   # llamadas del bot a su propia API, para diagnosticar
GASTO = {"usd": 0.0, "llamadas": 0, "bot_usd": 0.0, "bot_llamadas": 0, "bot_seg": 0.0}


def _contar_gasto(response, del_bot=False, segundos=0.0):
    try:
        datos = json.loads(response.content)
        uso, modelo = datos.get("usage") or {}, datos.get("model", "")
    except Exception:
        return
    base = next((v for k, v in PRECIOS.items() if modelo.startswith(k)), None)
    if not uso or not base:
        return
    cache = (uso.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    entrada = (uso.get("prompt_tokens") or 0) - cache
    usd = (entrada * base[0] + cache * base[1] + (uso.get("completion_tokens") or 0) * base[2]) / 1e6
    GASTO["usd"] += usd
    GASTO["llamadas"] += 1
    if del_bot:   # el bot llama sincrónico desde su hilo; paciente y juez, asíncrono
        GASTO["bot_usd"] += usd
        GASTO["bot_llamadas"] += 1
        GASTO["bot_seg"] += segundos


def _registrar_envio(cuerpo: dict):
    to = "".join(filter(str.isdigit, str(cuerpo.get("to", ""))))
    tipo = cuerpo.get("type")
    texto, opciones = "", []
    if tipo == "text":
        texto = cuerpo.get("text", {}).get("body", "")
    elif tipo == "interactive":
        inter = cuerpo.get("interactive", {})
        texto = (inter.get("body") or {}).get("text", "")
        accion = inter.get("action", {})
        opciones = [b.get("reply", {}).get("title", "") for b in accion.get("buttons", [])]
        for sec in accion.get("sections", []):
            opciones += [r.get("title", "") for r in sec.get("rows", [])]
    elif tipo == "template":
        texto = f"[plantilla {cuerpo.get('template', {}).get('name')}]"
    ENVIADOS.setdefault(to, []).append({
        "t": time.time(), "tipo": tipo, "texto": texto, "opciones": opciones,
        "lista": tipo == "interactive" and cuerpo.get("interactive", {}).get("type") == "list",
    })


def _respuesta_ycloud(request):
    return httpx.Response(200, json={"id": "sim-" + uuid.uuid4().hex[:10],
                                     "wamid": "wamid.SIMOUT" + uuid.uuid4().hex,
                                     "status": "accepted"}, request=request)


_send_async = httpx.AsyncClient.send
_send_sync = httpx.Client.send


async def _send_async_filtrado(self, request, *a, **k):
    host = request.url.host
    if host == "api.ycloud.com":
        if request.method == "POST" and request.content:
            _registrar_envio(json.loads(request.content))
        return _respuesta_ycloud(request)
    if host not in PERMITIDOS:
        raise RuntimeError(f"Salida bloqueada por el simulador: {host}")
    r = await _send_async(self, request, *a, **k)
    if host == "api.openai.com":
        await r.aread()
        _contar_gasto(r)
    return r


def _send_sync_filtrado(self, request, *a, **k):
    host = request.url.host
    if host == "api.ycloud.com":
        if request.method == "POST" and request.content:
            _registrar_envio(json.loads(request.content))
        return _respuesta_ycloud(request)
    if host not in PERMITIDOS:
        raise RuntimeError(f"Salida bloqueada por el simulador: {host}")
    t0 = time.time()
    try:
        r = _send_sync(self, request, *a, **k)
        if host == "127.0.0.1" and request.url.path.startswith("/api/bot/"):
            try:
                r.read()
                HERRAMIENTAS.append({"t": time.time(), "ruta": request.url.path,
                                     "pedido": json.loads(request.content or b"{}"),
                                     "estado": r.status_code, "respuesta": r.text[:600]})
            except Exception:
                pass
        if host == "api.openai.com":
            r.read()
            _contar_gasto(r)
        return r
    finally:
        if os.getenv("SIM_DEBUG") and time.time() - t0 > 2:
            print(f"[lento] {request.method} {request.url.path} {time.time() - t0:.1f}s", file=sys.stderr, flush=True)


httpx.AsyncClient.send = _send_async_filtrado
httpx.Client.send = _send_sync_filtrado

# El SDK de OpenAI 3.x usa httpx2, otra librería: se filtra y se mide igual.
try:
    import httpx2

    _send2_async, _send2_sync = httpx2.AsyncClient.send, httpx2.Client.send

    async def _send2_async_filtrado(self, request, *a, **k):
        if request.url.host not in PERMITIDOS:
            raise RuntimeError(f"Salida bloqueada por el simulador: {request.url.host}")
        r = await _send2_async(self, request, *a, **k)
        if request.url.host == "api.openai.com":
            await r.aread()
            _contar_gasto(r)
        return r

    def _send2_sync_filtrado(self, request, *a, **k):
        if request.url.host not in PERMITIDOS:
            raise RuntimeError(f"Salida bloqueada por el simulador: {request.url.host}")
        t0 = time.time()
        r = _send2_sync(self, request, *a, **k)
        if request.url.host == "api.openai.com":
            r.read()
            _contar_gasto(r, del_bot=True, segundos=time.time() - t0)
        return r

    httpx2.AsyncClient.send = _send2_async_filtrado
    httpx2.Client.send = _send2_sync_filtrado
except ImportError:
    pass


# Los gpt-5.x no aceptan temperature ni max_tokens (el bot manda los dos). Para
# poder compararlos sin tocar el bot, se adaptan acá; en producción haría falta
# el mismo ajuste en bot/ai_agent.py.
if MODELO_BOT.startswith("gpt-5"):
    from openai.resources.chat.completions import Completions

    _create = Completions.create

    def _create_adaptado(self, *a, **k):
        if str(k.get("model", "")).startswith("gpt-5"):
            k.pop("temperature", None)
            if "max_tokens" in k:
                k["max_completion_tokens"] = max(4000, k.pop("max_tokens"))
            # Con herramientas, chat.completions no acepta reasoning_effort.
            if os.getenv("SIM_RAZONAMIENTO"):
                k.setdefault("reasoning_effort", os.getenv("SIM_RAZONAMIENTO"))
        return _create(self, *a, **k)

    Completions.create = _create_adaptado


# ── Base de simulación ───────────────────────────────────────────────────────

def _crear_base_si_falta():
    from sqlalchemy import create_engine, text
    srv, nombre = URL_BASE_SIM.rsplit("/", 1)
    eng = create_engine(srv + "/postgres", isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        if not c.execute(text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": nombre}).first():
            c.execute(text(f'CREATE DATABASE "{nombre}"'))
    eng.dispose()


def _proximo(hoy, weekday: int, semana: int = 0):
    d = hoy + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d + timedelta(days=7 * semana)


def preparar_base(config: dict, personas: dict):
    _crear_base_si_falta()
    from sqlalchemy import text
    from backend.database import Base, engine, SessionLocal
    import backend.models  # noqa: F401
    from backend.models.professional import Professional
    from backend.models.schedule import ClinicSchedule, ProfessionalSchedule, ClinicHoliday
    from backend.models.tipo_consulta import TipoConsulta
    from backend.models.insurance import Insurance
    from backend.models.clinic_location import ClinicLocation
    from backend.models.patient import Patient
    from backend.models.appointment import Appointment, AppointmentStatus, AppointmentChannel
    from backend.models.config import AppConfig

    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    Base.metadata.create_all(bind=engine)
    from alembic.config import Config
    from alembic import command
    command.upgrade(Config("alembic.ini"), "head")

    # Algunas migraciones siembran datos de ejemplo; manda la foto de producción.
    db = SessionLocal()
    for modelo in (AppConfig, ClinicHoliday, ProfessionalSchedule, ClinicSchedule, TipoConsulta,
                   Insurance, ClinicLocation):
        db.query(modelo).delete()
    db.commit()
    hh = lambda s: dtime.fromisoformat(s)  # noqa: E731
    sede = config["sedes"][0]["name"]
    for s in config["sedes"]:
        db.add(ClinicLocation(name=s["name"], address=s["address"], phone=s["phone"],
                              is_active=s["is_active"]))
    profs = {}
    for p in config["profesionales"]:
        prof = Professional(full_name=p["full_name"], license_number=p["license_number"],
                            specialties=p["specialties"], locations=p.get("locations"),
                            is_active=p["is_active"])
        db.add(prof)
        db.flush()
        profs[p["full_name"].split()[-1]] = prof
        for b in p["grilla"]:
            db.add(ProfessionalSchedule(professional_id=prof.id, weekday=b["weekday"],
                                        start_time=hh(b["start_time"]), end_time=hh(b["end_time"]),
                                        is_active=True))
    for h in config["horario_clinica"]:
        db.add(ClinicSchedule(weekday=h["weekday"], start_time=hh(h["start_time"]),
                              end_time=hh(h["end_time"]), is_active=True))
    for f in config["feriados"]:
        db.add(ClinicHoliday(date=datetime.fromisoformat(f["date"]).date(),
                             description=f.get("description")))
    for t in config["tipos_consulta"]:
        db.add(TipoConsulta(nombre=t["nombre"], duracion_minutos=t["duracion_minutos"],
                            especialidad=t.get("especialidad"), sinonimos=t.get("sinonimos"),
                            is_active=t["is_active"]))
    for o in config["obras_sociales"]:
        db.add(Insurance(name=o["name"], code=o.get("code"), is_active=o["is_active"]))
    cfg = {
        "CHAIRS_PER_LOCATION": config["config_no_secreta"].get("CHAIRS_PER_LOCATION", "1"),
        "BOT_IS_ACTIVE": "true",
        "AI_PROVIDER": PROVEEDOR, "AI_PROVIDER_2": "none", "AI_PROVIDER_3": "none",
        ("OPENAI_API_KEY" if PROVEEDOR == "openai" else "OPENROUTER_API_KEY"): CLAVE,
        ("OPENAI_MODEL" if PROVEEDOR == "openai" else "OPENROUTER_MODEL"): MODELO_BOT,
        "ADMIN_NOTIFY_NUMBERS": NUMERO_AVISOS,
        "YCLOUD_API_KEY": "clave-falsa-simulador", "YCLOUD_FROM_PHONE": NUMERO_BOT,
        "PUBLIC_APP_URL": "https://odobot.cluna.ar",
    }
    for k, v in cfg.items():
        db.add(AppConfig(key=k, value=v))
    db.commit()

    hoy = datetime.now().date()

    def agendar(paciente, t, obra):
        dia = _proximo(hoy, t["dia"], t.get("semana", 0))
        db.add(Appointment(
            patient_id=paciente.id, professional_id=profs[t["profesional"]].id,
            start_time=datetime.combine(dia, hh(t["hora"])), duration_minutes=t["duracion"],
            reason=t["motivo"], location=sede, insurance_name=obra,
            status=AppointmentStatus.confirmed, channel=AppointmentChannel.phone,
        ))

    for e in personas["pacientes_existentes"]:
        pac = Patient(first_name=e["first_name"], last_name=e["last_name"], dni=e["dni"],
                      phone=e["phone"], insurance_name=e["insurance_name"])
        db.add(pac)
        db.flush()
        for t in e["turnos"]:
            agendar(pac, t, e["insurance_name"])
    relleno = Patient(first_name="Agenda", last_name="Ocupada", dni="99000001",
                      phone="+5492605559999", insurance_name="Particular")
    db.add(relleno)
    db.flush()
    for t in personas["agenda_ocupada"]:
        agendar(relleno, t, t["obra"])
    db.commit()
    db.close()


def foto_turnos():
    from backend.database import SessionLocal
    from backend.models.appointment import Appointment
    from backend.models.patient import Patient
    from backend.models.professional import Professional
    db = SessionLocal()
    try:
        filas = (db.query(Appointment, Patient, Professional)
                 .join(Patient, Appointment.patient_id == Patient.id)
                 .join(Professional, Appointment.professional_id == Professional.id).all())
        return {str(a.id): {
            "paciente": f"{p.first_name} {p.last_name}", "telefono": p.phone,
            "profesional": pr.full_name, "inicio": a.start_time.strftime("%a %d/%m %H:%M"),
            "inicio_iso": a.start_time.isoformat(), "minutos": a.duration_minutes,
            "motivo": a.reason, "obra": a.insurance_name, "estado": getattr(a.status, "value", a.status),
            "sede": a.location, "sobreturno": a.is_overbooking, "borrado": a.is_deleted,
        } for a, p, pr in filas}
    finally:
        db.close()


def diferencias(antes, despues):
    cambios = []
    for k, v in despues.items():
        if k not in antes:
            cambios.append({"accion": "nuevo", **v})
        elif antes[k] != v:
            dif = {c: f"{antes[k][c]} → {v[c]}" for c in v if antes[k][c] != v[c]}
            cambios.append({"accion": "modificado", "paciente": v["paciente"], "cambios": dif})
    return cambios


def _sin_tildes(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").lower()


def chequeos_de_profesional(turnos, config):
    """Especialista correcto, su grilla y la duración del tipo, para cada turno activo."""
    tipos = {_sin_tildes(t["nombre"]): t for t in config["tipos_consulta"]}
    profs = {p["full_name"]: p for p in config["profesionales"]}
    problemas = []
    for t in turnos.values():
        if t["estado"] in ("cancelled",) or t["borrado"]:
            continue
        ini = datetime.fromisoformat(t["inicio_iso"])
        fin = ini + timedelta(minutes=t["minutos"] or 30)
        prof = profs.get(t["profesional"])
        tipo = tipos.get(_sin_tildes(t["motivo"]))
        quien = f"{t['paciente']} {t['inicio']} {t['motivo']}"
        if not tipo:
            problemas.append(f"Motivo fuera de los tipos de consulta: {quien}")
        else:
            if tipo["duracion_minutos"] != t["minutos"]:
                problemas.append(f"Duración {t['minutos']}' ≠ {tipo['duracion_minutos']}' del tipo: {quien}")
            esp = tipo.get("especialidad")
            if esp and prof and _sin_tildes(esp) not in [_sin_tildes(x) for x in prof["specialties"]]:
                problemas.append(f"ESPECIALISTA EQUIVOCADO: {t['profesional']} no hace {esp} — {quien}")
        if prof:
            franjas = [(dtime.fromisoformat(b["start_time"]), dtime.fromisoformat(b["end_time"]))
                       for b in prof["grilla"] if b["weekday"] == ini.weekday()]
            if franjas and not any(a <= ini.time() and fin.time() <= b for a, b in franjas):
                problemas.append(f"FUERA DE LA GRILLA de {t['profesional']}: {quien}")
            if not franjas and prof["grilla"]:
                problemas.append(f"{t['profesional']} NO ATIENDE ese día: {quien}")
    return problemas


def chequeo_turno_esperado(conv, cambios):
    """Compara lo que quedó en la base con lo que el paciente quería. Sin IA."""
    esp = conv.get("turno_esperado")
    if not esp:
        return []
    nuevos = [c for c in cambios if c["accion"] == "nuevo"]
    problemas = []
    if "cantidad" in esp and len(nuevos) != esp["cantidad"]:
        problemas.append(f"Se esperaban {esp['cantidad']} turnos nuevos y quedaron {len(nuevos)}")
    if not nuevos:
        return problemas or ["No quedó ningún turno"]
    for n in nuevos:
        if esp.get("motivo") and n["motivo"] not in esp["motivo"]:
            problemas.append(f"Motivo {n['motivo']} (esperado {' o '.join(esp['motivo'])}) — {n['paciente']}")
        if esp.get("profesional") and esp["profesional"] not in n["profesional"]:
            problemas.append(f"Profesional {n['profesional']} (esperado {esp['profesional']}) — {n['paciente']}")
        if esp.get("obra") and n["obra"] != esp["obra"]:
            problemas.append(f"Cobertura {n['obra']} (esperada {esp['obra']}) — {n['paciente']}")
        if esp.get("paciente") and n["paciente"] != esp["paciente"]:
            problemas.append(f"A nombre de {n['paciente']} (esperado {esp['paciente']})")
    return problemas


def chequeos_globales(turnos, config):
    """Reglas duras sobre la agenda final: sillón, PAMI, grilla, feriados."""
    activos = [t for t in turnos.values()
               if t["estado"] not in ("cancelled", "canceled", "cancelado") and not t["borrado"]]
    problemas = []
    feriados = {f["date"] for f in config["feriados"]}
    for i, a in enumerate(activos):
        ia = datetime.fromisoformat(a["inicio_iso"])
        fa = ia + timedelta(minutes=a["minutos"] or 30)
        es_pami = (a["obra"] or "").upper() == "PAMI"
        if ia.weekday() == 4 and not es_pami:
            problemas.append(f"Viernes sin PAMI: {a['paciente']} {a['inicio']}")
        if es_pami and ia.weekday() != 4:
            problemas.append(f"PAMI fuera de viernes: {a['paciente']} {a['inicio']}")
        if ia.date().isoformat() in feriados:
            problemas.append(f"Turno en feriado: {a['paciente']} {a['inicio']}")
        for b in activos[i + 1:]:
            ib = datetime.fromisoformat(b["inicio_iso"])
            fb = ib + timedelta(minutes=b["minutos"] or 30)
            if ia < fb and ib < fa and not (a["sobreturno"] or b["sobreturno"]):
                problemas.append(f"SILLÓN SOLAPADO: {a['paciente']} {a['inicio']} ({a['minutos']}') "
                                 f"vs {b['paciente']} {b['inicio']} ({b['minutos']}')")
    return problemas


# ── Conversación ─────────────────────────────────────────────────────────────

def _firmar(raw: bytes) -> str:
    ts = str(int(time.time()))
    s = hmac.new(SECRETO_WEBHOOK.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return f"t={ts},s={s}"


async def mandar(cliente, telefono, nombre, texto, opcion=None, lista=False):
    wamid = "wamid.SIM" + uuid.uuid4().hex
    msg = {"id": wamid, "wamid": wamid, "from": "+" + telefono, "to": "+" + NUMERO_BOT,
           "sendTime": datetime.utcnow().isoformat() + "Z", "customerProfile": {"name": nombre}}
    if opcion:
        tipo = "list_reply" if lista else "button_reply"
        msg.update(type="interactive", interactive={"type": tipo, tipo: {"id": opcion[:20], "title": opcion}})
    else:
        msg.update(type="text", text={"body": texto})
    raw = json.dumps({"id": "evt" + uuid.uuid4().hex[:8], "type": "whatsapp.inbound_message.received",
                      "apiVersion": "v2", "createTime": msg["sendTime"],
                      "whatsappInboundMessage": msg}).encode()
    r = await cliente.post(f"http://127.0.0.1:{PUERTO}/api/whatsapp/webhook", content=raw,
                           headers={"Content-Type": "application/json", "YCloud-Signature": _firmar(raw)})
    return r.status_code


async def esperar_respuesta(telefono, desde_idx, tope=120.0, silencio=6.0):
    t0 = time.time()
    while time.time() - t0 < tope:
        lista = ENVIADOS.get(telefono, [])
        if len(lista) > desde_idx and time.time() - lista[-1]["t"] >= silencio:
            return lista[desde_idx:]
        await asyncio.sleep(0.5)
    return ENVIADOS.get(telefono, [])[desde_idx:]


def _texto_bot(m):
    t = m["texto"]
    if m["opciones"]:
        t += "\n[Opciones para tocar: " + " | ".join(m["opciones"]) + "]"
    return t


INSTRUCCIONES_PACIENTE = """Estás haciendo de PACIENTE que le escribe por WhatsApp al asistente de un
consultorio odontológico de San Rafael, Mendoza (Argentina). Hablá como una persona real argentina,
mensajes cortos de WhatsApp, voseo. No sos un asistente: no ayudes al bot ni le expliques cómo hacer su trabajo.

Tu personaje: {persona}
Tu objetivo: {objetivo}
Hoy es {hoy}.

Reglas del juego:
- Respondé SOLO con el mensaje que mandarías, sin comillas ni explicaciones.
- Si el bot te muestra "[Opciones para tocar: ...]" y querés elegir una, respondé exactamente
  TOCAR: <texto exacto de la opción>
- Si ya lograste tu objetivo, o te das cuenta de que no se puede y ya no tiene sentido seguir,
  despedite normalmente y agregá al final la palabra FIN.
- No inventes datos que tu personaje no sabría.
- Usá SOLO los datos de tu personaje (nombre, obra social, días). Si te muestran una lista
  y tu obra social no está, NO elijas otra: escribí el nombre de la tuya.
"""


async def jugar(cliente, ia, conv, hoy_txt, max_turnos=14):
    tel, nombre = conv["telefono"], conv["nombre"]
    sistema = INSTRUCCIONES_PACIENTE.format(persona=conv["persona"], objetivo=conv["objetivo"], hoy=hoy_txt)
    historia, transcript = [], []
    ultimo_bot = None
    for turno in range(max_turnos):
        r = await ia.chat.completions.create(
            model=MODELO_PACIENTE, temperature=0.7, max_tokens=300,
            messages=[{"role": "system", "content": sistema}] + historia
                     + ([] if historia else [{"role": "user", "content": "(Empezá vos la conversación.)"}]),
        )
        dicho = (r.choices[0].message.content or "").strip()
        fin = dicho.rstrip(" .!").endswith("FIN")
        dicho = re.sub(r"\s*FIN\s*[.!]*\s*$", "", dicho).strip()
        if not dicho and fin:
            break
        historia.append({"role": "assistant", "content": dicho})
        desde = len(ENVIADOS.get(tel, []))
        if dicho.upper().startswith("TOCAR:"):
            opcion = dicho.split(":", 1)[1].strip()
            transcript.append({"de": "paciente", "texto": f"[toca] {opcion}"})
            await mandar(cliente, tel, nombre, None, opcion=opcion,
                         lista=bool(ultimo_bot and ultimo_bot.get("lista")))
        else:
            partes = [p.strip() for p in dicho.split("||") if p.strip()]
            for i, p in enumerate(partes):
                transcript.append({"de": "paciente", "texto": p})
                await mandar(cliente, tel, nombre, p)
                if i < len(partes) - 1:
                    await asyncio.sleep(1.2)
        if fin:
            await esperar_respuesta(tel, desde, tope=20, silencio=4)
            for m in ENVIADOS.get(tel, [])[desde:]:
                transcript.append({"de": "bot", "texto": _texto_bot(m)})
            break
        nuevos = await esperar_respuesta(tel, desde)
        if not nuevos:
            transcript.append({"de": "bot", "texto": "⚠️ [SIN RESPUESTA en 120 s]"})
            historia.append({"role": "user", "content": "(El asistente no respondió.)"})
            continue
        for m in nuevos:
            transcript.append({"de": "bot", "texto": _texto_bot(m)})
        ultimo_bot = nuevos[-1]
        historia.append({"role": "user", "content": "\n\n".join(_texto_bot(m) for m in nuevos)})
    return transcript


REGLAS_JUEZ = """Reglas del consultorio (verdad de referencia):
- 2 profesionales: Dra. Elena Murad (ortodoncia, odontopediatría, conducto/endodoncia, limpieza, arreglos;
  atiende lunes, martes y viernes 9-12:30 y 17-20:30) y Dr. Martin Silvestro (cirugía, implantes, prótesis,
  extracción, limpieza, arreglos; miércoles 9-12:30, jueves y viernes 9-12:30 y 17-20:30).
- Un solo sillón: nunca dos turnos solapados, aunque sean de distinto profesional.
- PAMI solo viernes y los viernes solo PAMI. Al paciente NO se le explica esa regla interna.
- Clínica: lunes a viernes 9-12:30 y 17-20:30, miércoles sin tarde. Sábado y domingo cerrado. Feriados cerrado.
- Duraciones: Control y Limpieza 15'; Arreglos, Consulta por conducto, Extracción, Odontopediatría,
  Ortodoncia, Prótesis 30'; Cirugía y Conducto 60'.
- Conducto: siempre preguntar si es consulta/evaluación (30') o realizar el tratamiento (1 h) antes de ofrecer horarios.
- No pedir DNI ni teléfono; paciente nuevo: solo nombre y apellido. Identifica por WhatsApp.
- Cobertura obligatoria antes de ofrecer horarios; OSDE NO se atiende (está inactiva).
- No inventar horarios, precios, profesionales ni datos. Precios/urgencias/clínico: derivar a llamar.
- No repetir la misma pregunta; no pedir confirmaciones artificiales; elegir un horario ofrecido alcanza.
- No afirmar "te agendé/cancelé/reprogramé" si la base no lo muestra.
- Nunca revelar datos de otros pacientes ni actuar sobre turnos ajenos.
"""

INSTRUCCIONES_JUEZ = """Sos auditor de calidad de un asistente de turnos odontológicos por WhatsApp.
Evaluá la conversación con rigor y sin inventar: basate SOLO en el transcript y en los cambios de la base.

{reglas}

Caso: {id}
Objetivo del paciente: {objetivo}
Comportamiento esperado: {esperado}

Transcript:
{transcript}

Cambios en la base durante esta conversación:
{cambios}

Respondé SOLO un JSON con esta forma:
{{"resultado": "ok" | "con_problemas" | "falla",
  "objetivo_logrado": true|false,
  "coincide_bot_y_base": true|false,
  "problemas": [{{"gravedad": "alta|media|baja", "descripcion": "..."}}],
  "resumen": "una o dos frases"}}
"""


async def juzgar(ia, conv, transcript, cambios):
    try:
        return await _juzgar(ia, conv, transcript, cambios)
    except Exception as e:  # sin juez igual queda el transcript
        return {"resultado": "sin_juez", "resumen": f"El juez falló: {str(e)[:200]}"}


async def _juzgar(ia, conv, transcript, cambios):
    texto = "\n".join(f"{'PACIENTE' if m['de'] == 'paciente' else 'BOT'}: {m['texto']}" for m in transcript)
    r = await ia.chat.completions.create(
        model=MODELO_JUEZ, temperature=0, max_tokens=900,
        messages=[{"role": "user", "content": INSTRUCCIONES_JUEZ.format(
            reglas=REGLAS_JUEZ, id=conv["id"], objetivo=conv["objetivo"], esperado=conv["esperado"],
            transcript=texto, cambios=json.dumps(cambios, ensure_ascii=False, indent=1))}],
    )
    crudo = r.choices[0].message.content or ""
    m = re.search(r"\{.*\}", crudo, re.S)
    try:
        return json.loads(m.group(0)) if m else {"resultado": "?", "resumen": crudo[:300]}
    except json.JSONDecodeError:
        return {"resultado": "?", "resumen": crudo[:300]}


def _uso_openrouter():
    if PROVEEDOR != "openrouter":
        return None
    r = httpx.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {CLAVE}"}, timeout=20)
    return (r.json().get("data") or {}).get("usage")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--personas", required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--solo", default="")
    args = ap.parse_args()
    config = json.load(open(args.config, encoding="utf-8"))
    personas = json.load(open(args.personas, encoding="utf-8"))
    convs = personas["conversaciones"]
    if args.solo:
        ids = set(args.solo.split(","))
        convs = [c for c in convs if c["id"] in ids]

    preparar_base(config, personas)
    uso_inicial = _uso_openrouter()

    import uvicorn
    from openai import AsyncOpenAI
    from backend.main import app
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PUERTO,
                                             log_level="warning", lifespan="on"))
    tarea = asyncio.create_task(servidor.serve())
    while not servidor.started:
        await asyncio.sleep(0.2)

    ia = AsyncOpenAI(base_url=URL_IA, api_key=CLAVE)
    os.makedirs(args.salida, exist_ok=True)
    parcial = os.path.join(args.salida, datetime.now().strftime("sim_%Y-%m-%d_%H%M_parcial.jsonl"))
    hoy_txt = datetime.now().strftime("%A %d/%m/%Y")
    resultados = []
    async with httpx.AsyncClient(timeout=60) as cliente:
        solos = [c for c in convs if c.get("grupo") != "carrera"]
        carrera = [c for c in convs if c.get("grupo") == "carrera"]
        tandas = [[c] for c in solos] + ([carrera] if carrera else [])
        for tanda in tandas:
            if GASTO["usd"] >= TOPE_USD:
                print(f"TOPE DE GASTO alcanzado (USD {GASTO['usd']:.3f}): no se corren más.", flush=True)
                break
            antes = foto_turnos()
            t0 = time.time()
            bot0 = (GASTO["bot_usd"], GASTO["bot_llamadas"], GASTO["bot_seg"])
            h0 = len(HERRAMIENTAS)
            transcripts = await asyncio.gather(*(jugar(cliente, ia, c, hoy_txt) for c in tanda))
            await asyncio.sleep(3)
            cambios = diferencias(antes, foto_turnos())
            for conv, tr in zip(tanda, transcripts):
                propios = cambios  # en la carrera, los dos ven todos los cambios
                veredicto = await juzgar(ia, conv, tr, propios)
                fila = {"conv": conv, "transcript": tr, "cambios": propios,
                        "veredicto": veredicto, "segundos": round(time.time() - t0),
                        "turno_vs_esperado": chequeo_turno_esperado(conv, propios),
                        "modelo_bot": MODELO_BOT,
                        "herramientas": HERRAMIENTAS[h0:],
                        "bot_usd": round(GASTO["bot_usd"] - bot0[0], 5),
                        "bot_llamadas": GASTO["bot_llamadas"] - bot0[1],
                        "bot_seg_por_llamada": round((GASTO["bot_seg"] - bot0[2]) / max(1, GASTO["bot_llamadas"] - bot0[1]), 2)}
                resultados.append(fila)
                with open(parcial, "a", encoding="utf-8") as f:
                    f.write(json.dumps(fila, ensure_ascii=False) + "\n")
                vs = fila["turno_vs_esperado"]
                print(f"{conv['id']}: {'OK' if conv.get('turno_esperado') and not vs else ('; '.join(vs) if vs else 's/esperado')}"
                      f" | juez: {veredicto.get('resultado')}"
                      f"  [acumulado USD {GASTO['usd']:.3f}]", flush=True)

    final = foto_turnos()
    globales = chequeos_globales(final, config) + chequeos_de_profesional(final, config)
    uso_final = _uso_openrouter()
    servidor.should_exit = True
    await tarea

    os.makedirs(args.salida, exist_ok=True)
    marca = datetime.now().strftime("%Y-%m-%d_%H%M")
    json.dump({"resultados": resultados, "chequeos_globales": globales, "agenda_final": final,
               "costo_usd": GASTO["usd"] if PROVEEDOR == "openai" else (uso_final or 0) - (uso_inicial or 0),
               "modelos": {"bot": MODELO_BOT, "paciente": MODELO_PACIENTE, "juez": MODELO_JUEZ}},
              open(os.path.join(args.salida, f"sim_{marca}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("CHEQUEOS GLOBALES:", globales or "ninguno")
    print(f"COSTO USD: {GASTO['usd']:.4f} en {GASTO['llamadas']} llamadas" if PROVEEDOR == "openai"
          else f"COSTO USD: {((uso_final or 0) - (uso_inicial or 0)):.4f}")
    print("SALIDA:", os.path.join(args.salida, f"sim_{marca}.json"))


if __name__ == "__main__":
    asyncio.run(main())
