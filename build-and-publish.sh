#!/bin/bash
# Build and publish Docker image script

set -e  # Exit on error

# Configuration
IMAGE_NAME="co-tester"
DOCKER_USERNAME="kishore1305"
VERSION=${1:-"latest"}  # Use first argument as version, default to "latest"

echo "=================================="
echo "Building Co-Tester Docker Image"
echo "=================================="
echo "Image: $DOCKER_USERNAME/$IMAGE_NAME:$VERSION"
echo ""

# Build the image
echo "Step 1: Building Docker image..."
docker build -t $DOCKER_USERNAME/$IMAGE_NAME:$VERSION .

# Also tag as latest if version is specified
if [ "$VERSION" != "latest" ]; then
    echo "Step 2: Tagging as latest..."
    docker tag $DOCKER_USERNAME/$IMAGE_NAME:$VERSION $DOCKER_USERNAME/$IMAGE_NAME:latest
fi

echo ""
echo "Build complete!"
echo ""
echo "To test locally:"
echo "  docker run -p 5000:5000 --env-file .env $DOCKER_USERNAME/$IMAGE_NAME:$VERSION"
echo ""
echo "To publish to Docker Hub:"
echo "  1. docker login"
echo "  2. docker push $DOCKER_USERNAME/$IMAGE_NAME:$VERSION"
if [ "$VERSION" != "latest" ]; then
    echo "  3. docker push $DOCKER_USERNAME/$IMAGE_NAME:latest"
fi
echo ""

# Ask if user wants to publish
read -p "Do you want to publish to Docker Hub now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Publishing to Docker Hub..."
    docker push $DOCKER_USERNAME/$IMAGE_NAME:$VERSION
    if [ "$VERSION" != "latest" ]; then
        docker push $DOCKER_USERNAME/$IMAGE_NAME:latest
    fi
    echo "✅ Published successfully!"
    echo ""
    echo "Users can now pull with:"
    echo "  docker pull $DOCKER_USERNAME/$IMAGE_NAME:$VERSION"
fi
