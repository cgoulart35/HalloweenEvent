#!/bin/sh

PID=$(ps aux | grep "python3 HalloweenEvent" | grep -v grep | awk '{print $2}')
kill -9 $PID