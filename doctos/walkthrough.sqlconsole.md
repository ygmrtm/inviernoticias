# Walkthrough: Consola SQL & Gestión de Token de Respaldo (Fallback a DLX)

Se han completado los requerimientos solicitados para la plataforma:
1. **Consola SQL Ligera en el Módulo de Configuración**: Interfaz integrada en `/settings` y endpoint `POST /api/sql/execute` para interactuar directamente con la base de datos interna SQLite (`inviernoticias.db`).
2. **Gestión de Token de Respaldo (Fallback por Cuota 429)**: Detección automática de agotamiento de cuota en la cuenta principal de Gemini (`GEMINI_API_KEY`), conmutación fluida a una cuenta de respaldo (`GEMINI_BACKUP_API_KEY`), y envío de la solicitud de análisis a la **cola DLX de RabbitMQ** si ambos tokens agotan su cuota.

---

## 💻 1. Consola SQL Ligera para SQLite

### Backend ([`app/db.py`](file:///Users/yg/Documents/GitHub/inviernoticias/app/db.py) y [`app/main.py`](file:///Users/yg/Documents/GitHub/inviernoticias/app/main.py))
- Función `execute_sql_query(query_str)`:
  - Clasifica automáticamente la sentencia:
    - **Consultas de lectura** (`SELECT`, `PRAGMA`, `EXPLAIN`, `WITH`): Extrae columnas y filas, cronometra la ejecución en milisegundos y devuelve formato JSON estructurado.
    - **Sentencias de mutación / DDL** (`INSERT`, `UPDATE`, `DELETE`, etc.): Ejecuta el comando, aplica `commit` a la transacción y retorna el número de filas afectadas (`rowsAffected`).
    - **Manejo de errores**: Captura excepciones de SQLite y retorna mensaje descriptivo con código HTTP 400.
- Endpoint REST: `POST /api/sql/execute` con payload `{"query": "SELECT * FROM feeds;"}`.

### Frontend SSR Accesible ([`app/templates/settings.html`](file:///Users/yg/Documents/GitHub/inviernoticias/app/templates/settings.html))
- Editor con tipografía monoespaciada de alto contraste (`.sql-editor`).
- Chips de acceso rápido para consultas frecuentes (ej. `SELECT * FROM feeds;`, `COUNT(articles);`, `PRAGMA table_info(articles);`).
- Tabla responsiva con desplazamiento horizontal (`.table-scroll`) que renderiza los resultados preservando la consulta enviada.
- Controlador de formulario: `POST /action/settings/sql` y soporte para URL directa `GET /settings?sql=...`.

---

## 🔑 2. Gestión de Tokens de API de Gemini & Fallback a DLX

### Flujo de Conmutación por Cuota ([`app/gemini.py`](file:///Users/yg/Documents/GitHub/inviernoticias/app/gemini.py))
1. **Detección de Cuota Agotada (`is_quota_exceeded_error`)**:
   - Monitorea errores HTTP `429`, códigos de error `RESOURCE_EXHAUSTED` o mensajes relativos a límites de cuota/rate limit.
2. **Fallback Primario &rarr; Secundario**:
   - Al recibir una solicitud, el sistema intenta procesarla con el token principal (`GEMINI_API_KEY`).
   - Si la API de Gemini responde con `429 / RESOURCE_EXHAUSTED`, se marca la bandera `gemini_primary_quota_exceeded = "true"`, se conmuta el token activo a `"backup"` y se reintenta inmediatamente la llamada con `GEMINI_BACKUP_API_KEY`.
   - Si el token secundario tiene éxito, la respuesta incluye `"tokenUsed": "backup"`.
3. **Agotamiento Total & Enrutamiento a DLX ([`app/worker.py`](file:///Users/yg/Documents/GitHub/inviernoticias/app/worker.py))**:
   - Si el token de respaldo **también agota su cuota** (o no hay token de respaldo configurado), se lanza la excepción `AllTokensQuotaExceededError`.
   - En el worker de RabbitMQ (`on_analyze_message`), esta excepción es capturada específicamente:
     ```python
     except gemini.AllTokensQuotaExceededError as quota_err:
         logger.error(f"[Worker] Cuota agotada en ambos tokens. Despachando a DLX: {quota_err}")
         rabbitmq.handle_consumer_failure(
             channel=ch,
             method=method,
             properties=properties,
             body_bytes=body,
             error_message=f"QUOTA_EXHAUSTED: {quota_err}"
         )
     ```
   - El mensaje se envía a `articles.dlx.exchange` con clave `article.dlx.retry` y retraso TTL (`x-message-ttl`), permitiendo que el artículo se reintente automáticamente más tarde cuando la cuota de la API se haya restablecido.
   - En peticiones síncronas directas (`/api/analyze`), se devuelve un código HTTP `429 Too Many Requests`.

### Diagnóstico & Configuración Web
- En `/settings`, se visualizan tarjetas de diagnóstico para ambos tokens con indicadores de estado:
  - Token Principal: `[⭐ Activo]` o `[⚠️ Cuota Agotada (429)]`.
  - Token de Respaldo: `[✓ Listo]`, `[🔄 Activo en Fallback]` o `[⚠️ Cuota Agotada (429)]`.
  - Formularios para actualizar credenciales y botón para reiniciar el estado de cuotas.

---

## 📮 3. Colección de Postman Actualizada

La colección [`postman/Inviernoticias_API.postman_collection.json`](file:///Users/yg/Documents/GitHub/inviernoticias/postman/Inviernoticias_API.postman_collection.json) se ha ampliado a **8 carpetas** y **29 peticiones probadas**:
- **`05. AI Analysis (Gemini + Grounding)`**:
  - `Get Gemini Tokens Status` (`GET /api/tokens/status`)
  - `Update Gemini Tokens` (`POST /api/tokens`)
  - `Reset Token Quota Status` (`POST /api/tokens/reset-quota`)
- **`08. Database & SQL Console`**:
  - `Execute SQL Query (SELECT)` (`POST /api/sql/execute`)
  - `Execute SQL Query (PRAGMA)` (`POST /api/sql/execute`)
  - `Execute SQL Statement (Mutation)` (`POST /api/sql/execute`)

---

## 🧪 4. Resultados de Pruebas

Se ejecutaron pruebas unitarias e integrales para verificar el comportamiento:
1. `db.execute_sql_query` &rarr; Consultas `SELECT`, `PRAGMA`, mutaciones `INSERT`/`DELETE` y manejo de errores sintácticos aprobados.
2. `POST /api/sql/execute` &rarr; 200 OK en consultas válidas y 400 Bad Request en errores SQL.
3. Fallback de Gemini (Simulación de Cuota 429):
   - **Caso A (Primario 429 &rarr; Fallback a Respaldo)**: Detecta 429, conmuta a respaldo y completa el análisis exitosamente (`tokenUsed: "backup"`).
   - **Caso B (Ambos tokens 429)**: Lanza `AllTokensQuotaExceededError`.
   - **Caso C (Worker DLX)**: Captura `AllTokensQuotaExceededError` y despacha el mensaje a la cola DLX de reintentos con TTL.
4. Renderizado SSR de `/settings` &rarr; Visualización correcta de tablas SQL, chips interactivos y tarjetas de salud de tokens.
