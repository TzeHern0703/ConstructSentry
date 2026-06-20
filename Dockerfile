# ConstructSentry — single-service image: build the React dashboard, then run
# the FastAPI backend which also serves the built frontend.

# Stage 1 — build the dashboard
FROM node:20-slim AS web
WORKDIR /web
COPY dashboard/package*.json ./
RUN npm install
COPY dashboard/ ./
RUN npm run build

# Stage 2 — Python backend + the built frontend
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=web /web/dist ./dashboard/dist
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8000}"]
