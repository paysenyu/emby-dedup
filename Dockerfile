FROM node:20-alpine AS frontend-build

WORKDIR /frontend

COPY frontend/package.json /frontend/package.json
RUN npm install

COPY frontend /frontend
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY --from=frontend-build /frontend/dist /app/frontend_dist

ENV PYTHONPATH=/app/backend
ENV APP_DB_PATH=/config/app.db
ENV APP_CONFIG_PATH=/config/config.json
ENV APP_LOGS_DIR=/config/logs

EXPOSE 5055

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5055"]
