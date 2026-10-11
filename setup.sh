#!/usr/bin/env bash
# Linux / macOS equivalent of setup.bat + run.bat:  ./setup.sh  then  ./run.sh
set -e
cd "$(dirname "$0")"
python3 -m venv venv
. venv/bin/activate
if [ -d wheels ]; then pip install --no-index --find-links wheels -r requirements.txt; else pip install -r requirements.txt; fi
python train_models.py
echo "Setup finished. Start the app with ./run.sh"
