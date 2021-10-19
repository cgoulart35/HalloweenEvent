#!/bin/sh

cd ~/Code/GoulartEvents/HalloweenEvent

python 'HalloweenEventApi/api.py' &
python 'HalloweenEventWebApp/app.py' &
