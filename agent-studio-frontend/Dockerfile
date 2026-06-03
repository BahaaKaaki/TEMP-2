# Multi-stage build for Agent Studio Frontend
FROM node:20-alpine as builder

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
# Use npm install to automatically resolve platform-specific packages (Linux vs Windows)
RUN npm install

# Copy source files
COPY . .

# Accept build argument for API URL (empty for Docker since paths already include /api)
ARG VITE_API_BASE_URL=

# Create .env file with the build argument
RUN echo "VITE_API_BASE_URL=${VITE_API_BASE_URL}" > .env

# Build the application
RUN npm run build

# Production stage with nginx
FROM nginx:alpine

# Copy built files from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost/ || exit 1

# Start nginx
CMD ["nginx", "-g", "daemon off;"]

