from datetime import datetime


# Live "has The Long Night ended?" check shared by the API and web app. The apps no
# longer shut themselves down at SCHEDULED_SHUTDOWN_TIME; instead they keep running
# (so the containers stay up / can auto-restart) and switch into a closed/ended state.
# Computed against the current time on each call rather than via a one-shot scheduler
# job, so it stays correct across container restarts.
def eventHasEnded(shutdownTime):
    return datetime.now() >= datetime.strptime(shutdownTime, "%m/%d/%y %I:%M:%S %p")
