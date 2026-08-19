# 🦷 Silprodent

> Sistema de gestión integral para consultorios odontológicos con DentiBot (IA autónoma para gestión de turnos por WhatsApp).

## 🚀 Stack Tecnológico

| Componente | Tecnología |
|------------|-----------|
| **Backend** | Python + FastAPI |
| **Base de Datos** | PostgreSQL 16 + SQLAlchemy 2.0 + Alembic |
| **Frontend** | HTML5 + CSS3 Nativo (SPA) + JavaScript Vanilla |
| **Canal** | WhatsApp vía YCloud (webhook firmado) |
| **IA / Bot** | OpenAI function calling nativo (GPT-4o-mini) · cascada OpenRouter/Groq |
| **Deploy** | Docker + Docker Compose + Dokploy |

## 📦 Estructura del Proyecto

```
dentibot/
├── frontend/              # SPA (Dashboard, Agenda, Odontograma)
│   ├── app_clinic/        # Vistas operativas
│   ├── app_admin/         # Panel de administración
│   └── shared_components/ # Componentes reutilizables
├── backend/               # FastAPI (API REST + Serve SPA)
│   ├── routers/admin/     # Rutas solo admin
│   ├── routers/clinic/    # Rutas operativas
│   ├── models/            # SQLAlchemy models
│   └── schemas/           # Pydantic schemas
├── bot/                   # DentiBot (agente IA + canal Telegram, hoy apagado)
│   └── tools/             # Tools del agente IA
├── database/migrations/   # Alembic
├── docker-compose.yml     # Despliegue
└── Dockerfile             # Build
```

## 🔐 Primer acceso

El seed crea dos usuarios: `admin@dentalstudio.com` (admin) y
`recepcion@dentalstudio.com` (recepción).

**Las passwords no están fijadas en el código.** Se toman de las variables
`ADMIN_PASSWORD` y `RECEPCION_PASSWORD`; si no están definidas, el arranque
genera una al azar y la escribe **una sola vez** en el log del contenedor:

```bash
docker compose logs backend | grep "🔑"
```

En una instalación anterior a este cambio las cuentas quedaron con las
passwords de ejemplo. Rotalas una vez:

```bash
python scripts/cambiar_password.py --listar          # marca las que siguen débiles
python scripts/cambiar_password.py --email admin@dentalstudio.com
```

## 🐳 Deploy en Dokploy

### 1. Variables de entorno (configurar en Dokploy)

```env
POSTGRES_USER=dentibot
POSTGRES_PASSWORD=tu_password_segura
POSTGRES_DB=dentibot
DATABASE_URL=postgresql://dentibot:tu_password_segura@db:5432/dentibot
SECRET_KEY=generar-clave-segura-produccion
BOT_API_KEY=generar-clave-bot-api
OPENAI_API_KEY=sk-tu-api-key-de-openai
TELEGRAM_BOT_TOKEN=tu-bot-token-de-telegram
```

### 2. Deploy

```bash
# En Dokploy, seleccionar "Docker Compose" y apuntar al repositorio de GitHub
# Dokploy detectará automáticamente el docker-compose.yml

# O manualmente:
git push origin main
# → Dokploy auto-deploy
```

### 3. Local (desarrollo)

```bash
# Clonar
git clone <tu-repo>
cd odoAntigravity

# Levantar servicios
docker compose up --build -d

# Abrir en http://localhost:8000
```

## 📋 Módulos

- **Dashboard**: estadísticas, turnos del día
- **Agenda**: CRUD de turnos con timeline, filtros por profesional/sede/estado
- **Pacientes**: CRUD con búsqueda, soft-delete
- **Odontograma Digital**: notación FDI (11-48), 5 caras por diente, colores rojo/azul, símbolos X/O/Corona/Prótesis
- **DentiBot**: agente IA autónomo para agendar/cancelar/reprogramar/consultar turnos por WhatsApp
- **Admin**: gestión de usuarios (RBAC), profesionales, sedes, obras sociales

## 🤖 DentiBot - Flujo de conversación

1. Saludo → pregunta sede (San Rafael / Alvear)
2. Motivo de consulta
3. Enrutamiento automático:
   - **Extracciones/Implantes/Prótesis** → Dr. Silvestro
   - **Ortodoncia/Conductos** → Dra. Murad (consulta 1ra o 2da)
4. Datos obligatorios: Nombre, Apellido, DNI, Obra Social, Teléfono
5. Confirmación y agendamiento

## 🔒 Seguridad

- JWT en todas las rutas de API
- RBAC: `admin`, `receptionist`, `doctor`
- Soft-delete en todos los registros críticos
- API Key separada para el Bot
- CORS configurado
