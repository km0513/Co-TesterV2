# 🐳 Co-Tester - Docker Deployment Guide

This guide helps you run Co-Tester using Docker, with all dependencies (Playwright, system libraries) pre-installed.

## 📋 Prerequisites

- **Docker Desktop** (Windows/Mac) or **Docker Engine** (Linux)
  - Download: https://www.docker.com/products/docker-desktop
- **Docker Compose** (usually included with Docker Desktop)

## 🚀 Quick Start for Users

### Option 1: Using Docker Compose (Recommended)

1. **Create a directory for Co-Tester:**
   ```bash
   mkdir co-tester-app
   cd co-tester-app
   ```

2. **Download the docker-compose.yml file**
   ```bash
   # Download from the repository
   wget https://raw.githubusercontent.com/your-repo/Co-Tester/main/docker-compose.yml
   ```

3. **Create .env file with your settings:**
   ```bash
   # Copy example file
   cp .env.docker.example .env
   
   # Edit with your values
   nano .env  # or use any text editor
   ```

   **Required values:**
   - `SECRET_KEY` - Random string (min 32 characters)
   - `GOOGLE_API_KEY` - Your Google Gemini API key

4. **Start Co-Tester:**
   ```bash
   docker-compose up -d
   ```

5. **Access the application:**
   - Open http://localhost:5000 in your browser
   - Login with Jira OAuth or use guest mode

### Option 2: Using Docker Run

```bash
docker run -d \
  --name co-tester \
  -p 5000:5000 \
  -e SECRET_KEY="your-secret-key-here" \
  -e GOOGLE_API_KEY="your-google-api-key" \
  -e GOOGLE_API_MODEL="gemini-2.0-flash-exp" \
  -v $(pwd)/data/instance:/app/instance \
  -v $(pwd)/data/uploads:/app/uploads \
  -v $(pwd)/data/reports:/app/reports \
  your-dockerhub-username/co-tester:latest
```

## 🔄 Updating Co-Tester

### With Docker Compose:
```bash
# Pull latest version
docker-compose pull

# Restart with new version
docker-compose up -d
```

### With Docker Run:
```bash
# Stop current container
docker stop co-tester
docker rm co-tester

# Pull latest image
docker pull your-dockerhub-username/co-tester:latest

# Start with new version (use same command as initial setup)
docker run -d --name co-tester ...
```

**Your data is safe!** - All user data persists in the mounted volumes.

## 🛠️ Management Commands

### View logs:
```bash
# Docker Compose
docker-compose logs -f

# Docker Run
docker logs -f co-tester
```

### Stop Co-Tester:
```bash
# Docker Compose
docker-compose stop

# Docker Run
docker stop co-tester
```

### Start Co-Tester:
```bash
# Docker Compose
docker-compose start

# Docker Run
docker start co-tester
```

### Restart Co-Tester:
```bash
# Docker Compose
docker-compose restart

# Docker Run
docker restart co-tester
```

### Check status:
```bash
# Docker Compose
docker-compose ps

# Docker Run
docker ps | grep co-tester
```

## 📁 Data Persistence

Co-Tester stores data in the following locations:

- `./data/instance/` - Database (SQLite)
- `./data/uploads/` - Uploaded files
- `./data/reports/` - Test reports
- `./data/playwright-output/` - Recorded Playwright scripts
- `./data/codegen-output/` - Generated test code
- `./data/logs/` - Application logs

**These folders persist across updates**, so your data is safe when you update the Docker image.

## 🔧 Troubleshooting

### Port already in use:
```bash
# Change port 5000 to something else, e.g., 8080
docker run -p 8080:5000 ...
# Access at http://localhost:8080
```

### Permission issues (Linux):
```bash
# Fix ownership of data folders
sudo chown -R $USER:$USER ./data
```

### Container won't start:
```bash
# Check logs for errors
docker logs co-tester

# Check if port is available
netstat -ano | findstr :5000  # Windows
lsof -i :5000                  # Mac/Linux
```

### Reset everything:
```bash
# Stop and remove container
docker-compose down

# Remove all data (⚠️ WARNING: This deletes everything!)
rm -rf ./data

# Start fresh
docker-compose up -d
```

## 🔐 Security Best Practices

1. **Never commit .env file** - It contains secrets
2. **Use strong SECRET_KEY** - Generate with: `openssl rand -hex 32`
3. **Protect API keys** - Don't share your Google API key
4. **Regular updates** - Pull latest images for security patches
5. **Firewall** - If exposing publicly, use proper firewall rules

## 🌐 Production Deployment

For production deployment on a server:

1. **Use a reverse proxy** (nginx/Caddy) for HTTPS
2. **Set production environment variables**
3. **Configure domain callback URL** for Jira OAuth
4. **Set up automated backups** of ./data folder
5. **Use proper secrets management** (Docker secrets, vault)

Example nginx configuration:
```nginx
server {
    listen 80;
    server_name yourdomain.com;
    
    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 📞 Support

- **Issues**: https://github.com/your-repo/Co-Tester/issues
- **Documentation**: See main README.md

## 📝 Version History

Check available versions:
```bash
# View all tags
docker images your-dockerhub-username/co-tester
```

Use specific version:
```bash
docker pull your-dockerhub-username/co-tester:v1.0.0
```

---

**Happy Testing! 🚀**
