#!/bin/bash
nohup venv/bin/python main.py > logs/bot.log 2>&1 & echo $! > .bot_pid
echo "Bot started (PID: $(cat .bot_pid))"
