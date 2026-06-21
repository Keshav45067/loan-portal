#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Augmen — Frontend & Nginx Auto-Setup Script
# Must be run with sudo/root privileges on the VM
# ═══════════════════════════════════════════════════════════

set -e

# Verify root privileges
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root/sudo: sudo bash setup_web.sh"
  exit 1
fi

BASE_DIR="/var/www/augmen/testing-services"

# ─── 1. Install PM2 Globally ───
if ! command -v pm2 &> /dev/null; then
    echo "⚙️ Installing PM2 globally..."
    npm install -g pm2
fi

# ─── 2. Build Next.js Frontend ───
echo "🎨 Building Next.js frontend..."
cd "${BASE_DIR}/frontend"

# Get VM's public IP to configure build env variables
PUBLIC_IP=$(curl -s https://ipinfo.io/ip || echo "localhost")
echo "  Detected public IP: $PUBLIC_IP"

export NEXT_PUBLIC_API_URL="http://${PUBLIC_IP}"
export NEXT_PUBLIC_WS_URL="ws://${PUBLIC_IP}"

echo "  Installing frontend packages..."
npm install

echo "  Building static Next.js production files..."
npm run build

# ─── 3. Run Frontend via PM2 ───
echo "🚀 Running frontend server on port 3001 via PM2..."
pm2 delete augmen-frontend 2>/dev/null || true
# Run Next.js binary directly for robust process management and host binding
pm2 start node_modules/next/dist/bin/next --name "augmen-frontend" -- start -p 3001 -H 127.0.0.1
pm2 save

# ─── 4. Configure Nginx Proxy ───
echo "⚙️ Setting up Nginx configuration..."
NGINX_CONF="/etc/nginx/sites-available/augmen"

cat <<EOF > "$NGINX_CONF"
server {
    listen 80;
    server_name _;

    # 1. Frontend Proxy
    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
    }

    # 2. API Gateway HTTP routes
    location /api/ {
        proxy_pass http://127.0.0.1:8889;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # 3. API Gateway WebSockets (/ws/voice)
    location /ws/ {
        proxy_pass http://127.0.0.1:8889;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 86400; # Keep WS alive for long calls
    }
}
EOF

# ─── 5. Enable configuration and restart Nginx ───
echo "🔄 Activating Nginx configurations..."
# Remove default config
rm -f /etc/nginx/sites-enabled/default

# Link config
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/augmen

# Test Nginx syntax
nginx -t

# Restart Nginx
systemctl restart nginx

# ─── 6. Configure Firewall ───
if command -v ufw &> /dev/null; then
    echo "🛡️ Configuring Firewall (UFW)..."
    ufw allow OpenSSH
    ufw allow 'Nginx Full'
    ufw --force enable
fi

echo ""
echo "🎉 Frontend is active via PM2, and Nginx reverse proxy configured!"
echo "   You can now access your app at: http://$PUBLIC_IP"
