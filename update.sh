#!/bin/bash
# Co-Tester Update Script for Users

set -e

echo "=================================="
echo "Co-Tester Update Script"
echo "=================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running!"
    echo "Please start Docker Desktop and try again."
    exit 1
fi

echo "📥 Pulling latest Co-Tester version..."
docker-compose pull

echo ""
echo "🔄 Restarting with new version..."
docker-compose up -d

echo ""
echo "✅ Update complete!"
echo ""
echo "Co-Tester is now running the latest version."
echo "Access it at: http://localhost:5000"
echo ""

# Show version/logs
echo "Recent logs:"
docker-compose logs --tail=20

echo ""
echo "To view full logs: docker-compose logs -f"
