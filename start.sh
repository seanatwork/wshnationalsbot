#!/bin/bash
# Start both healthcheck and bot
python healthcheck.py &
python main.py
