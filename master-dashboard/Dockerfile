FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
ENV ASSISTANT_API_URL=http://assistant-api:8000 \
    NGINX_ENVSUBST_FILTER=^ASSISTANT_API_URL$
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
RUN ASSISTANT_API_URL=http://127.0.0.1:8000 /docker-entrypoint.sh nginx -t
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
