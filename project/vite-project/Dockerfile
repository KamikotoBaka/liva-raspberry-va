# Frontend Dockerfile for LIVA Voice Assistant - Optimized for Raspberry Pi 5
# Multi-stage build: Build stage + Production stage

# Build Stage
FROM node:20-alpine AS builder

# Set metadata
LABEL maintainer="M&M Software GmbH"
LABEL description="LIVA Voice Assistant - Frontend (Vite) - Raspberry Pi Edition"

# Set working directory
WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install all dependencies (including devDependencies for build)
RUN npm ci

# Copy application files
COPY . .

# Build the Vite application
RUN npm run build

# Production Stage
FROM node:20-alpine

# Set metadata
LABEL maintainer="M&M Software GmbH"
LABEL description="LIVA Voice Assistant - Frontend (Vite) - Raspberry Pi Edition - Production"

WORKDIR /app

# Install http-server for serving static files
RUN npm install -g http-server

# Copy built application from builder stage
COPY --from=builder /app/dist ./dist

# Create startup script that injects API URL into index.html
RUN echo '#!/bin/sh' > /app/start.sh && \
    echo 'API_BASE_URL=${VITE_API_BASE_URL:-http://liva-assistant:8000}' >> /app/start.sh && \
    echo 'sed -i "s|<head>|<head><script>window.API_BASE_URL='"'"'"$API_BASE_URL"'"'"'</script>|g" /app/dist/index.html' >> /app/start.sh && \
    echo 'http-server dist -p 5173 -c-1 --gzip' >> /app/start.sh && \
    chmod +x /app/start.sh

# Expose port for frontend
EXPOSE 5173

# Environment variables
ENV NODE_ENV=production
ENV VITE_API_BASE_URL=http://liva-assistant:8000

# Start with the script
CMD ["/app/start.sh"]
