#!/bin/bash
# Exit on error
set -e

# Install NVM
echo "Installing NVM..."
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

# Load NVM
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# Install Node 20
echo "Installing Node.js..."
nvm install 20
nvm use 20

# Initialize Next.js in a directory called 'frontend'
echo "Initializing Next.js..."
npx -y create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm

echo "Setup complete!"
