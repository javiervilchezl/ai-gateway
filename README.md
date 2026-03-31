# AI Gateway

API de orquestacion y aplicacion web para analisis de texto y PDF con autenticacion JWT.

<img width="1920" height="947" alt="FireShot Capture 009 - AI Gateway -  localhost" src="https://github.com/user-attachments/assets/801a8d9b-be3c-42c0-8fef-3e02a00b638f" />
<img width="1920" height="1734" alt="FireShot Capture 008 - AI Gateway -  localhost" src="https://github.com/user-attachments/assets/190d255d-d967-423c-9969-c86eacce1c0b" />
<img width="1920" height="1734" alt="FireShot Capture 008 - AI Gateway -  localhost" src="https://github.com/user-attachments/assets/6da0105f-e825-4268-a30b-030dfb492ab3" />
<img width="1920" height="947" alt="FireShot Capture 009 - AI Gateway -  localhost" src="https://github.com/user-attachments/assets/7fb9fd42-b14a-441d-999b-fa0d0c9aa650" />


## Que hace este proyecto

- centraliza el acceso a capacidades NLP en un unico punto
- ofrece login y control de acceso con JWT
- aplica rate limiting en login y endpoints de analisis
- integra una interfaz web para analisis de texto y documentos PDF
- persiste usuarios en MySQL con contrasenas hasheadas

## Dependencias de microservicios

Este proyecto funciona junto a los siguientes repositorios:

- classifier-service: https://github.com/javiervilchezl/classifier-service
- intent-service: https://github.com/javiervilchezl/intent-service
- pdf-service: https://github.com/javiervilchezl/pdf-service

El gateway consume esos servicios por HTTP para completar el flujo de analisis.

## OpenAI y Groq: como se usan

El gateway no llama directamente a OpenAI/Groq. Quien consume esas APIs son los microservicios:

- `pdf-service`
- `classifier-service`
- `intent-service`

En cada microservicio puedes elegir proveedor por `.env` con:

- `PROVIDER=openai` o `PROVIDER=groq`
- `OPENAI_API_KEY` y `OPENAI_MODEL`
- `GROQ_API_KEY` y `GROQ_MODEL`

Asi, puedes tener por ejemplo `pdf-service` en OpenAI y `intent-service` en Groq, segun costo, latencia o calidad esperada.

## Arquitectura funcional

```
browser / CLI
     │
     ▼
ai-gateway  ──  auth · rate-limit · routing
     ├──▶ pdf-service
     ├──▶ classifier-service
     └──▶ intent-service
```

## Estructura

```text
ai-gateway/
├── backend/
├── frontend/
├── .env.example
└── docker-compose.yml
```

## Endpoints principales (backend)

- `POST /api/v1/auth/login`
- `POST /api/v1/analyze`
- `POST /api/v1/analyze-pdf-file`
- `GET /health`

## Seguridad

- JWT para acceso desde frontend
- limitacion de peticiones por IP y endpoint
- API key opcional para clientes servidor-a-servidor
- microservicios internos no expuestos al exterior en despliegue compuesto

## Gestion de secretos

- todos los secretos deben vivir en `.env` local
- no se deben subir archivos `.env` al repositorio
- `docker-compose.yml` no define claves reales por defecto
- antes de publicar en GitHub, rota cualquier clave que se haya usado en local

## Variables clave

- `JWT_SECRET_KEY`
- `AUTH_REQUIRE_JWT`
- `DATABASE_URL`
- `ADMIN_DEFAULT_USERNAME`
- `ADMIN_DEFAULT_PASSWORD`
- `PDF_SERVICE_URL`
- `CLASSIFIER_SERVICE_URL`
- `INTENT_SERVICE_URL`
- `VITE_API_BASE_URL`

## Ejecucion local

1. Copia el archivo de ejemplo:

```bash
cp .env.example .env
```

2. Levanta backend y frontend:

```bash
docker compose up --build
```

Servicios:

- backend: `http://localhost:8000`
- frontend: `http://localhost:5173`

## Flujo funcional resumido

1. Login en frontend para obtener JWT.
2. Peticion al gateway con bearer token.
3. Validacion de seguridad en backend (JWT + rate limit).
4. Enrutamiento al microservicio que corresponda.
5. Respuesta unificada hacia frontend/CLI.

## Pruebas

Backend:

```bash
cd backend
pytest
```

Frontend:

```bash
cd frontend
npm test -- --run
```

Cobertura al 100%.
