#!/bin/sh
# Boot launcher for the deploy watcher. Invoked from /etc/rc.local (mirrors GPUH's start.sh):
#   su - cgoulart -c "sh /home/cgoulart/Code/HalloweenEvent/scripts/start.sh"
cd /home/cgoulart/Code/HalloweenEvent || exit 1
mkdir -p Logs
nohup sh scripts/deploy-watcher.sh >> Logs/deploy-watcher.log 2>&1 &
