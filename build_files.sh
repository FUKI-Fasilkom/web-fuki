#!/bin/bash
echo "Building the project..."

# Install dependencies if not already installed
if ! command -v pip &> /dev/null; then
    python3 -m ensurepip
    python3 -m pip install --upgrade pip
fi

python3 -m pip install -r requirements.txt

# Collect static files
python3 manage.py collectstatic --noinput --clear

echo "Build completed!"