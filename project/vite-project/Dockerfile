# Frontend Dockerfile for LIVA Voice Assistant - Optimized for Raspberry Pi 5
# Multi-stage build: Build stage + Production stage

# Build Stage
FROM node:20-alpine AS builder

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

# Expose port for frontend
EXPOSE 5173

# Environment variables
ENV NODE_ENV=production

# Serve the static bundle
CMD ["http-server", "dist", "-p", "5173", "-c-1", "--gzip"]
