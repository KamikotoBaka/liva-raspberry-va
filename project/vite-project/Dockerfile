# Frontend Dockerfile for LIVA Voice Assistant - Optimized for Raspberry Pi 5
# Multi-stage build: Build stage + Production stage

# Build Stage
FROM node:20-bookworm-slim AS builder

# Set metadata
LABEL maintainer="M&M Software GmbH"
LABEL description="LIVA Voice Assistant - Frontend (Vite) - Raspberry Pi Edition"

# Set working directory
WORKDIR /app

# Backend URL baked into the frontend bundle at build time.
ARG VITE_API_BASE_URL=https://api.livapi.local
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

# Copy package files
COPY package.json package-lock.json ./

# Install all dependencies (including devDependencies for build)
# Retry once to avoid transient esbuild install issues on some container filesystems.
RUN npm ci --no-audit --no-fund || (npm cache clean --force && npm ci --no-audit --no-fund)

# Copy application files
COPY . .

# Build the Vite application
RUN npm run build

# Production Stage
FROM node:20-bookworm-slim

# Set metadata
LABEL maintainer="M&M Software GmbH"
LABEL description="LIVA Voice Assistant - Frontend (Vite) - Raspberry Pi Edition - Production"

WORKDIR /app

# Install http-server for serving static files
RUN npm install -g http-server

# Copy built application from builder stage
COPY --from=builder /app/dist ./dist

# Runtime API URL (can be overridden when starting container)
ARG VITE_API_BASE_URL=https://api.livapi.local
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

# Create startup script to inject runtime API URL into index.html
RUN echo '#!/bin/sh' > /app/start.sh && \
    echo 'API_URL=${VITE_API_BASE_URL:-https://api.livapi.local}' >> /app/start.sh && \
    echo 'sed -i "s|<head>|<head><script>window.API_BASE_URL='"'"'"$API_URL"'"'"'</script>|g" /app/dist/index.html' >> /app/start.sh && \
    echo 'http-server dist -p 5173 -c-1 --gzip' >> /app/start.sh && \
    chmod +x /app/start.sh

# Expose port for frontend
EXPOSE 5173

# Environment variables
ENV NODE_ENV=production

# Start with startup script
CMD ["/app/start.sh"]
