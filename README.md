# 🦷 Dental Studio Pro

> Sistema de gestión integral para consultorios odontológicos con DentiBot (IA autónoma para gestión de turnos vía Telegram).

## 🚀 Stack Tecnológico

| Componente | Tecnología |
|------------|-----------|
| **Backend** | Python + FastAPI |
| **Base de Datos** | PostgreSQL 16 + SQLAlchemy 2.0 + Alembic |
| **Frontend** | HTML5 + CSS3 Nativo (SPA) + JavaScript Vanilla |
| **IA / Bot** | LangChain + OpenAI GPT-4o-mini + Aiogram 3 |
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
├── bot/                   # DentiBot (LangChain + Telegram)
│   └── tools/             # Tools del agente IA
├── database/migrations/   # Alembic
├── docker-compose.yml     # Despliegue
└── Dockerfile             # Build
```

## 🔐 Credenciales por defecto

| Rol | Email | Password |
|-----|-------|----------|
| Admin | admin@dentalstudio.com | admin123 |
| Recepcionista | recepcion@dentalstudio.com | recepcion123 |

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
- **DentiBot**: agente IA autónomo para agendar/cancelar/reprogramar/consultar turnos por Telegram
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
