#!/bin/sh

cd ~/Code/GoulartEvents/HalloweenEvent

python3 'HalloweenEventApi/api.py' &
python3 'HalloweenEventWebApp/app.py' &
