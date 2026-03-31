# AI Gateway Backend

Backend FastAPI que centraliza autenticacion, seguridad y orquestacion entre microservicios NLP.

## Responsabilidad

- exponer una API unica para clientes web
- autenticar usuarios con JWT
- aplicar rate limiting por endpoint
- enrutar peticiones a `pdf-service`, `classifier-service` e `intent-service`
- unificar respuesta funcional y metadatos tecnicos
- mantener observabilidad (latencia, proveedor, coste estimado)

## Endpoints

### Health

- `GET /health`

### Auth

- `POST /api/v1/auth/login`

Body:

```json
{
	"username": "admin",
	"password": "tu_password"
}
```

Respuesta:

```json
{
	"access_token": "...",
	"token_type": "bearer",
	"expires_in": 3600
}
```

### Analisis de texto

- `POST /api/v1/analyze`

```json
{
	"input_type": "text",
	"content": "I want a refund for my subscription",
	"mode": "both",
	"labels": ["support", "sales", "complaint"]
}
```

### Analisis de PDF (upload)

- `POST /api/v1/analyze-pdf-file`
- `multipart/form-data`, campo `file`

## Seguridad

- JWT obligatorio cuando `AUTH_REQUIRE_JWT=true`
- usuarios almacenados en MySQL
- password hashing con bcrypt
- seed de usuario admin por defecto en arranque (si no existe)
- API key de gateway opcional para escenarios server-to-server
- rate limit para login y API

## Variables de entorno clave

- `JWT_SECRET_KEY`
- `AUTH_REQUIRE_JWT`
- `DATABASE_URL`
- `ADMIN_DEFAULT_USERNAME`
- `ADMIN_DEFAULT_PASSWORD`
- `RATE_LIMIT_ENABLED`
- `RATE_LIMIT_REQUESTS`
- `RATE_LIMIT_LOGIN_REQUESTS`
- `PDF_SERVICE_URL`
- `CLASSIFIER_SERVICE_URL`
- `INTENT_SERVICE_URL`

## Ejecucion local

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Ejecucion con Docker (gateway completo)

Desde `ai-gateway/`:

```bash
docker compose up --build
```

## Pruebas

```bash
pip install -r requirements-dev.txt
pytest
```

Cobertura configurada al 100%.

