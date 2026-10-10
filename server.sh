#!/usr/bin/env bash

PROJECT="$HOME/Desktop/MY_GIT/Tv_docker"

gnome-terminal --title="TV Docker - Backend" -- bash -lc "cd '$PROJECT/backend' && source '$HOME/miniconda3/bin/activate' && uvicorn main:app --host 0.0.0.0 --port 8010; echo; read -n 1 -s -r -p 'Press any key to exit...'"

gnome-terminal --title="TV Docker - Frontend" -- bash -lc "cd '$PROJECT/frontend' && npm install && npm run dev -- --host 0.0.0.0 --port 5173; echo; read -n 1 -s -r -p 'Press any key to exit...'"

wait