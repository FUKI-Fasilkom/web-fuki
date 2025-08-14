#!/bin/bash
echo "Building the project..."

# Install pip terlebih dahulu
python3.9 -m ensurepip --upgrade

# Install dependencies
python3.9 -m pip install --upgrade pip
python3.9 -m pip install -r requirements.txt

# Collect static files
python3.9 manage.py collectstatic --noinput --clear

echo "Build completed!"