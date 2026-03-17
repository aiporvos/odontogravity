# 🏗️ Skill 03: System Architecture

## Arquitectura General

```
┌──────────────────────────────────────────────────────────┐
│                     INTERNET                              │
│                                                          │
│   ┌─────────────┐        ┌──────────────────────┐       │
│   │  Telegram    │        │   Browser (SPA)      │       │
│   │  WhatsApp    │        │   (Recepción/Doctor) │       │
│   └──────┬──────┘        └──────────┬───────────┘       │
│          │                          │                    │
│   ┌──────▼──────┐        ┌──────────▼───────────┐       │
│   │   DentiBot  │        │    FastAPI Backend    │       │
│   │   (Aiogram  │  HTTP  │    (Serve SPA +      │       │
│   │   LangChain)├───────►│     REST API)        │       │
│   └─────────────┘        └──────────┬───────────┘       │
│                                     │                    │
│                          ┌──────────▼───────────┐       │
│                          │   PostgreSQL 16       │       │
│                          │   (pgdata volume)     │       │
│                          └──────────────────────┘       │
└──────────────────────────────────────────────────────────┘
```

## Seguridad (RBAC)

```
admin          → /api/admin/*   + /api/clinic/*
receptionist   → /api/clinic/*
doctor         → /api/clinic/*
bot (api-key)  → /api/bot/*
```

## Principios
1. **Soft-Delete**: Nunca se ejecuta DELETE. Se usa `is_deleted = True`.
2. **Frontend desacoplado**: El SPA se sirve como archivos estáticos desde FastAPI.
3. **Bot aislado**: La carpeta `/bot` se comunica con `/backend` solo via HTTP.
4. **Docker Compose**: Todo se despliega con un solo comando.
5. **Migraciones**: Alembic gestiona cambios en la BD.

## Servicios Docker
| Servicio | Puerto | Descripción |
|----------|--------|-------------|
| db | 5432 | PostgreSQL con volume persistente |
| backend | 8000 | FastAPI + SPA Frontend |
| bot | 8443 | DentiBot Telegram |

## Deploy en Dokploy
1. Conectar repo de GitHub en Dokploy
2. Seleccionar tipo: **Docker Compose**
3. Configurar variables de entorno en el panel
4. Deploy automático en cada push a main
