FROM nginx:1.27-alpine

# Copy static files
COPY frontend/static /usr/share/nginx/html/static

# Copy nginx config
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
