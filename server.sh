#!/usr/bin/env bash

# Open Terminal 1
x-terminal-emulator -e bash -c '
    cd backend && source $HOME/miniconda3/bin/activate && uvicorn main:app --port 8010
    echo
    read -n 1 -s -r -p "Press any key to exit..."
' &

# Open Terminal 2
x-terminal-emulator -e bash -c '
    cd frontend && npm install && npm run dev  
    echo
    read -n 1 -s -r -p "Press any key to exit..."
' &

wait