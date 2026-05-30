# Detector de Red Flags y Sesgo en Noticias (POC)

Esta es una Prueba de Concepto (POC) de una aplicación diseñada para analizar textos de noticias o avisos, detectando posibles "banderas rojas" (red flags), nivel de confianza y sesgos cognitivos o políticos, utilizando Inteligencia Artificial.

El diseño está pensado con consideraciones de accesibilidad para adultos mayores: fuentes grandes, alto contraste e interfaz sencilla.

## Estructura del Proyecto

El proyecto se divide en dos partes:
- \`frontend/\`: Aplicación en React + Vite.
- \`backend/\`: Servidor Node.js + Express que se comunica con la API de Google Gemini.

## Requisitos

- Node.js instalado (v18+ recomendado).
- Una clave de API de Google Gemini (Gemini API Key).

## Configuración y Ejecución

### 1. Configurar el Backend

Navega a la carpeta \`backend\`:
\`\`\`bash
cd backend
\`\`\`

Crea un archivo \`.env\` basado en \`.env.example\` y añade tu API Key:
\`\`\`bash
cp .env.example .env
\`\`\`
Abre \`.env\` y reemplaza \`YOUR_GEMINI_API_KEY_HERE\` con tu clave real.

Instala las dependencias y corre el servidor:
\`\`\`bash
npm install
npm start
\`\`\`
El servidor correrá en \`http://localhost:3001\`.

### 2. Configurar el Frontend

Abre otra terminal y navega a la carpeta \`frontend\`:
\`\`\`bash
cd frontend
\`\`\`

Instala las dependencias y arranca el servidor de desarrollo:
\`\`\`bash
npm install
npm run dev
\`\`\`
La aplicación web se abrirá en tu navegador (por defecto en \`http://localhost:5173\`).

## Uso

1. Copia el texto completo de una noticia o aviso que quieras analizar.
2. Pégalo en el cuadro de texto principal de la aplicación.
3. Haz clic en "Analizar Texto".
4. Revisa los resultados, que incluirán un Nivel de Confianza (0-100%), el Sesgo Detectado y una lista de Banderas Rojas si las hay.

## Próximos Pasos (Futuras Versiones)
- Implementar web scraping para analizar URLs directamente.
- Búsqueda de noticias relacionadas para contrastar fuentes.
- Sistema de base de datos para guardar análisis previos.
