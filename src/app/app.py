#region IMPORTS
import os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, send_from_directory

from src.app.views import views, parentDir, getScoreboard
from src.app.properties import WebAppPropertiesManager
#endregion

# create event scheduler for shutdown and refreshing scoreboard
def shutDownApplication():
    os.system("kill -15 1")

sched = BackgroundScheduler(daemon=True)
sched.add_job(shutDownApplication, 'date', run_date = datetime.strptime(WebAppPropertiesManager.SCHEDULED_SHUTDOWN_TIME, "%m/%d/%y %I:%M:%S %p"))
sched.add_job(getScoreboard, 'interval', seconds = 30)
sched.start()

app = Flask(__name__)
app.secret_key = WebAppPropertiesManager.SECRET_KEY
app.register_blueprint(views, url_prefix="/")
app.add_url_rule('/favicon.ico', view_func = lambda: send_from_directory(parentDir + '/src/common', 'favicon-pumpkin.ico'))
app.run(host='0.0.0.0',
        port=WebAppPropertiesManager.WEBAPP_PORT,
        # TODO
        ssl_context=('/HalloweenEvent/server.crt', '/HalloweenEvent/server.key')
        )