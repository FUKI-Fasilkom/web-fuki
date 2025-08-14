#!/bin/bash
echo "Building the project..."

# Pastikan pip tersedia dan upgrade
python -m ensurepip --upgrade
python -m pip install --upgrade pip

# Install dependencies
python -m pip install -r requirements.txt

# Collect static files
python manage.py collectstatic --noinput --clear

echo "Build completed!"