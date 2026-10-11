# Frontend — builds the Vite SPA and serves it via nginx on Cloud Run ($PORT).
# VITE_API_URL is baked at BUILD time (passed as --build-arg by cd.yml).
FROM node:22-alpine AS builder

WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL=http://localhost:8000/api/v1
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html
EXPOSE 8080
# Cloud Run injects $PORT; nginx listens on 8080 by default (see nginx.conf).
CMD ["nginx", "-g", "daemon off;"]
