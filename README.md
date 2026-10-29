# ❄️ Inviernoticias .mx

Detector de Sátira, Veracidad y Sesgo en Medios y Noticias de México, impulsado por Inteligencia Artificial (**Google Gemini 2.5 Flash** con **Search Grounding**).

> **Arquitectura 100% Python & Cero JavaScript**: Toda la plataforma (backend, frontend SSR y tareas de inferencia) corre en Python nativo con **FastAPI**, plantillas **Jinja2** y **CSS puro**. Sin Node.js, sin npm y sin una sola línea de JavaScript en el cliente, optimizado para máxima accesibilidad (diseño para adultos mayores con alto contraste y tipografía legible).

---

## 🚀 Características Principales

- **Detección de Sátira ("Mock-ticia" vs "Real-ticia")**: Clasifica automáticamente notas de portales de humor (como *El Deforma*) y noticias reales.
- **Medidores de Sarcasmo y Veracidad**: Calificación de 0 a 100% representada visualmente en CSS accesible.
- **Premio México Mágico 🇲🇽**: Reconoce eventos y noticias surrealistas que desafían el sentido común.
- **Contexto Cultural & Explicación para Extranjeros**: Desglose de jerga, modismos, refrán popular mexicano y citas históricas relevantes.
- **Search Grounding con Google**: Contraste de fuentes y enlaces en tiempo real para verificar información.
- **Exportación a Notion**: Sincronización directa de artículos analizados hacia una base de datos en Notion.
- **Sincronización Automatizada de RSS**: Agrega, gestiona y sincroniza múltiples fuentes de noticias.
- **Análisis Directo de Texto**: Pega titulares o cadenas de mensajes para analizarlos al instante.
- **Selección de Modelos de IA & Recomendaciones**: Permite seleccionar dinámicamente y persistir en base de datos el modelo de Gemini activo (`gemini-2.5-flash` recomendado, `gemini-2.5-pro`, `gemini-2.0-flash`, `gemini-2.0-flash-lite`, etc.) con soporte para Search Grounding.
- **Gestión de Token de Respaldo y Fallback Automático por Cuota (429)**: Si el token principal de **Google Gemini** agota su cuota de peticiones (`Error 429 / RESOURCE_EXHAUSTED`), el sistema conmuta automáticamente al token secundario de respaldo (`GEMINI_BACKUP_API_KEY`). Si ambos tokens agotan su cuota, la solicitud de análisis del artículo es enviada a la **cola DLX de RabbitMQ** para reprocesarse automáticamente más tarde.
- **Consola SQL Ligera Integrada en Configuración**: Permite inspeccionar y consultar directamente la base de datos interna SQLite (`inviernoticias.db`) con soporte para sentencias `SELECT`, `PRAGMA`, `INSERT`, `UPDATE` y `DELETE`, con visualización de resultados en tablas accesibles y métricas de ejecución.
- **Planificador Parametrizado (APScheduler)**: Configuración flexible de cuándo iniciar la primera ejecución (hora fija `HH:MM` o fecha ISO), intervalo en horas (`interval_hours`), hora diaria programada y ejecución inmediata opcional.
- **CronJob Automatizado cada 24 Horas**: Proceso periódico que calcula la ventana de las últimas 24 horas (`start_date = now - 24h`, `end_date = now`), sincroniza **todas las fuentes RSS registradas** en la tabla de feeds y encola artículos sin analizar para su procesamiento concurrente.
- **Pipeline Asíncrono con RabbitMQ (Topic Exchange & DLX)**:
  - Enrutamiento por tipo de artículo hacia el exchange de tópicos `articles.exchange`.
  - Worker 1 (*Analyzer Consumer*): ejecuta inferencia con Gemini y despacha solicitud a Notion enrutada según tipo (`mockticia` vs `realticia`).
  - Worker 2 (*Notion Consumer*): publica el artículo calificado en Notion.
  - Reprocesamiento con Dead Letter Exchange (**DLX**): si un mensaje falla, se redirige a una cola de retraso con TTL para reintentar automáticamente más tarde.

---

## 📁 Estructura del Proyecto

```
inviernoticias/
├── app/
│   ├── __init__.py
│   ├── main.py              # Aplicación FastAPI, vistas SSR y endpoints REST
│   ├── db.py                # Base de datos SQLite (feeds, artículos, análisis y settings)
│   ├── gemini.py            # Modelos Gemini, SDK Google GenAI y Search Grounding
│   ├── scheduler.py         # Planificador parametrizable con APScheduler
│   ├── worker.py            # Workers de consumo de colas RabbitMQ
│   ├── cron.py              # Lógica de sincronización 24h y RabbitMQ dispatch
│   ├── rabbitmq.py          # Topología RabbitMQ, exchanges, colas y DLX
│   ├── rss.py               # Sincronizador de feeds RSS (feedparser)
│   ├── notion.py            # Conector con la API de Notion
│   ├── static/
│   │   └── style.css        # CSS accesible, alto contraste y responsivo (sin JS)
│   └── templates/
│       ├── base.html        # Estructura base con navegación accesible
│       ├── index.html       # Monitoreo de artículos, filtros y medidores
│       ├── feeds.html       # Administración de fuentes RSS
│       ├── direct.html      # Análisis directo de texto libre
│       ├── settings.html    # Configuración de modelo de IA y planificador
│       └── article_detail.html # Ficha técnica completa del análisis
├── postman/
│   ├── Inviernoticias_API.postman_collection.json # Colección de pruebas de Postman
│   └── Inviernoticias_Environment.postman_environment.json # Entorno local
├── requirements.txt         # Dependencias Python
├── run.sh                   # Script para iniciar en local
├── Dockerfile               # Contenedor ligero Python 3.12
├── docker-compose.yml       # Orquestación Docker
├── deploy.sh                # Script de despliegue a servidor
└── .env.example             # Plantilla de variables de entorno
```

---

## ⚙️ Requisitos

- Python 3.10 o superior.
- Clave de API de Google Gemini (`GEMINI_API_KEY`).
- Token y Base de Datos de Notion (`NOTION_TOKEN`, `NOTION_DATABASE_ID` - opcional).

---

## 🛠️ Instalación y Ejecución Local

### 1. Clonar y configurar entorno virtual

```bash
git clone https://github.com/yg/inviernoticias.git
cd inviernoticias

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

Copia la plantilla y coloca tus claves:
```bash
cp .env.example .env
```

Contenido de `.env`:
```env
PORT=3001
GEMINI_API_KEY=tu_clave_de_gemini
NOTION_TOKEN=secret_tu_notion_token
NOTION_DATABASE_ID=tu_database_id_notion
```

### 3. Iniciar la aplicación

Ejecuta el script:
```bash
./run.sh
```
O directamente con Uvicorn:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 3001 --reload
```

Abre en tu navegador: **[http://localhost:3001](http://localhost:3001)**

---

## 🐳 Ejecución con Docker

```bash
docker compose up -d --build
```
La aplicación quedará disponible en el puerto `3001` con persistencia de base de datos en un volumen Docker.

---

## 📮 Pruebas con Postman

Se incluye la colección completa para probar todos los endpoints REST:

- **Colección**: [`postman/Inviernoticias_API.postman_collection.json`](file:///Users/yg/Documents/GitHub/inviernoticias/postman/Inviernoticias_API.postman_collection.json)
- **Entorno**: [`postman/Inviernoticias_Environment.postman_environment.json`](file:///Users/yg/Documents/GitHub/inviernoticias/postman/Inviernoticias_Environment.postman_environment.json)

### Endpoints disponibles:
| Endpoint | Método | Descripción |
| :--- | :---: | :--- |
| `/api/health` | `GET` | Estado del servicio |
| `/api/feeds` | `GET` / `POST` | Listar y crear fuentes RSS |
| `/api/feeds/:id` | `DELETE` | Eliminar fuente RSS |
| `/api/feeds/sync` | `POST` | Sincronizar artículos desde RSS |
| `/api/articles` | `GET` | Listar artículos (soporta paginación y filtros) |
| `/api/articles/:id` | `GET` | Detalle de un artículo |
| `/api/models` | `GET` | Lista de modelos Gemini adecuados y modelo activo |
| `/api/models/default` | `POST` | Establecer y persistir modelo de IA predeterminado |
| `/api/analyze` | `POST` | Análisis directo de texto libre con IA |
| `/api/articles/:id/analyze` | `POST` | Análisis inteligente de un artículo guardado |
| `/api/articles/:id/notion` | `POST` / `GET` | Exportar análisis a Notion |
| `/api/scheduler/start` | `POST` | Iniciar / parametrizar planificador (inicio y周期) |
| `/api/scheduler/stop` | `POST` | Detener planificador en segundo plano |
| `/api/scheduler/status` | `GET` | Estado detallado, próxima ejecución y config |
| `/api/cron/trigger` | `POST` | Disparar manualmente el CronJob de 24 horas |
| `/api/cron/status` | `GET` | Estado del planificador APScheduler |
| `/api/queue/status` | `GET` | Monitoreo y conteo de mensajes en colas de RabbitMQ |
| `/api/tokens/status` | `GET` | Estado y salud de cuota de tokens Gemini (principal y respaldo) |
| `/api/tokens` | `POST` | Configurar o actualizar claves API de Gemini |
| `/api/tokens/reset-quota` | `POST` | Restablecer estado de cuota y reactivar token principal |
| `/api/sql/execute` | `POST` | Ejecutar comandos SQL directamente en SQLite interno |
