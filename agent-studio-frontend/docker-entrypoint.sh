#!/bin/sh
set -e

# Set default backend URL if not provided
export BACKEND_URL=${BACKEND_URL:-http://agent-studio-backend:8000}

echo "🔧 Configuring nginx with backend URL: ${BACKEND_URL}"

# Substitute environment variables in nginx config template
envsubst '${BACKEND_URL}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf

echo "✅ Nginx configuration complete"
cat /etc/nginx/conf.d/default.conf

# Start nginx
exec nginx -g 'daemon off;'
