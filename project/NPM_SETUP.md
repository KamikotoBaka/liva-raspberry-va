# Nginx Proxy Manager (NPM) Setup Guide for LIVA

## Overview
Nginx Proxy Manager is now running as a reverse proxy with HTTPS support for your LIVA stack.

## Access Information

### Nginx Proxy Manager Admin Panel
- **URL**: http://localhost:81
- **Default Credentials**:
  - Email: `admin@example.com`
  - Password: `changeme`
  - **⚠️ Change these immediately after first login!**

### Services Behind NPM

| Service | Internal URL | Proxy To |
|---------|--------------|----------|
| Frontend (Vite) | http://liva-frontend:5173 | http://yourdomain.com |
| Backend API | http://liva-assistant:8000 | http://yourdomain.com/api |
| MQTT Broker | Direct Port | 1883 (not proxied) |
| Ollama | http://ollama:11434 | Internal only |

## Initial Setup Steps

1. **Access NPM Admin Panel**:
   ```bash
   # Open browser
   http://localhost:81
   # Login with default credentials (admin@example.com / changeme)
   ```

2. **Change Admin Password**:
   - Click on "Admin Users" in the top right
   - Edit the admin user and set a strong password

3. **Add SSL Certificate (Let's Encrypt)**:
   - Go to "SSL Certificates" → "Add SSL Certificate"
   - Select "Let's Encrypt"
   - Enter your domain name
   - Accept terms and continue

4. **Create Proxy Host for Frontend**:
   - Go to "Proxy Hosts" → "Add Proxy Host"
   - **Domain Names**: `yourdomain.com` (without www)
   - **Scheme**: `http`
   - **Forward Hostname/IP**: `liva-frontend`
   - **Forward Port**: `5173`
   - **Cache Assets**: Enable
   - **Block Common Exploits**: Enable
   - Go to **SSL** tab:
     - **SSL Certificate**: Select your Let's Encrypt cert
     - **Force SSL**: Enable
     - **HTTP/2 Support**: Enable
   - Save

5. **Create Proxy Host for Backend API**:
   - Go to "Proxy Hosts" → "Add Proxy Host"
   - **Domain Names**: `api.yourdomain.com`
   - **Scheme**: `http`
   - **Forward Hostname/IP**: `liva-assistant`
   - **Forward Port**: `8000`
   - Go to **SSL** tab:
     - **SSL Certificate**: Select your Let's Encrypt cert
     - **Force SSL**: Enable
   - Save

## Docker Compose Services

```yaml
# Nginx Proxy Manager (Reverse Proxy)
nginx-proxy-manager:
  - Ports: 80 (HTTP), 443 (HTTPS), 81 (Admin)
  - Database: MariaDB (npm-db)
  - Volumes: npm_data, npm_letsencrypt

# MariaDB (NPM Database)
npm-db:
  - Internal service
  - Stores proxy configuration and SSL certs

# LIVA Frontend (Vite App)
liva-frontend:
  - Port 5173 (internal, proxied via NPM)

# LIVA Backend (FastAPI)
liva-assistant:
  - Port 8000 (internal, proxied via NPM)

# Ollama (LLM)
ollama:
  - Port 11434 (internal only)

# Mosquitto (MQTT Broker)
mosquitto:
  - Port 1883 (MQTT), 9001 (WebSocket)
```

## Accessing Your Application

- **Frontend**: https://yourdomain.com
- **Backend API**: https://api.yourdomain.com
- **Admin Panel**: http://localhost:81

## Docker Commands

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f nginx-proxy-manager

# Rebuild and start
docker compose up -d --build

# Stop all services
docker compose down

# Remove all volumes (WARNING: deletes data)
docker compose down -v
```

## Important Notes

1. **Security**:
   - Change default NPM credentials immediately
   - Use strong Let's Encrypt certificates
   - Keep Docker images updated

2. **Database Credentials**:
   - Update `npm_password_change_me` and `npm_root_password_change_me` in docker-compose.yml before first run
   - These should be changed to secure values

3. **Port Mapping**:
   - Port 80 (HTTP) → Auto-redirects to HTTPS
   - Port 443 (HTTPS) → Your secure traffic
   - Port 81 → Admin panel (keep this on localhost for security)

4. **SSL Certificates**:
   - Stored in `./npm_letsencrypt` volume
   - Auto-renews within 30 days of expiration
   - Persists across container restarts

## Troubleshooting

**NPM not responding**:
```bash
docker compose logs npm-db
docker compose restart nginx-proxy-manager npm-db
```

**Certificate issues**:
- Check domain DNS points to your server
- Ensure ports 80 and 443 are accessible
- Check NPM logs: `docker compose logs nginx-proxy-manager`

**Internal network issues**:
- All services communicate via `liva-network` bridge network
- Service hostnames resolve internally: `liva-frontend`, `liva-assistant`, etc.

