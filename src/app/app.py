#region IMPORTS
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, send_from_directory
from flask_toastr import Toastr

from src.app.views import views, parentDir, expireServerSessions
from src.app.properties import WebAppPropertiesManager
#endregion

# The web app never shuts down: views.py serves the closed/ended page whenever the
# season isn't open (see eventIsOpen gating), so the container keeps running year-round.
# This scheduler only refreshes server-side sessions; the API owns the season lifecycle.
sched = BackgroundScheduler(daemon=True)
sched.add_job(expireServerSessions, 'interval', seconds = 60)
sched.start()

app = Flask(__name__)
app.secret_key = WebAppPropertiesManager.SECRET_KEY
app.register_blueprint(views, url_prefix="/")
app.add_url_rule('/favicon.ico', view_func = lambda: send_from_directory(parentDir + '/src/common', 'favicon-pumpkin.ico'))
toastr = Toastr(app)
app.config['TOASTR_OPACITY'] = False
app.run(host='0.0.0.0',
        port=WebAppPropertiesManager.WEBAPP_PORT,
        # TODO
        ssl_context=('/HalloweenEvent/server.crt', '/HalloweenEvent/server.key')
        )