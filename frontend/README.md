# AI Gateway Frontend

SPA React para operar el gateway de NLP con un flujo claro de autenticacion y analisis.

## Funcionalidad

- login con usuario/password contra el backend
- gestion de sesion via JWT bearer token
- analisis de texto
- analisis de documentos PDF
- visualizacion de resumen, temas, categoria, intencion, latencia, proveedor y coste estimado

## Seguridad

- el frontend no contiene secretos de infraestructura
- no usa API key embebida en variables `VITE_*`
- autenticacion basada en JWT emitido por backend

## Stack

- React 19
- TypeScript
- Vite
- Vitest
- Testing Library

## Ejecucion local

```bash
npm install
npm run dev
```

## Variables

- `VITE_API_BASE_URL`: URL base del backend del gateway (ejemplo: `http://localhost:8000`)

## Pruebas

```bash
npm test
```

Cobertura configurada con umbral del 100%.
