#!/bin/bash
# Load NVM if it exists
[ -s "$HOME/.nvm/nvm.sh" ] && \. "$HOME/.nvm/nvm.sh"

echo "Installing missing dependencies in frontend..."
cd frontend
npm install

echo "Committing and pushing to main..."
cd ..
git add .
# We use a simple commit, ignore error if nothing to commit
git commit -m "Phase 0.2: Frontend Foundation with Dark Mode & Supabase integration" || true

# Push to main (or master, checking which branch we are on)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push origin $BRANCH
