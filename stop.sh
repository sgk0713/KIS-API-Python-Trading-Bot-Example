#!/bin/bash
if [ -f .bot_pid ]; then
    kill $(cat .bot_pid) && rm .bot_pid
    echo "Bot stopped"
else
    echo "No .bot_pid file found"
fi
