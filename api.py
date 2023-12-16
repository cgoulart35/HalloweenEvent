#region IMPORTS
import pathlib
import os
import logging
import sys
import json
from datetime import datetime
from hypercorn.logging import AccessLogAtoms
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, abort, send_from_directory, request
from flask_restful import Api, Resource
from flask_cors import CORS

from src.common import queries
from src.api.properties import APIPropertiesManager
from src.common.firebase import FirebaseService
#endregion

class CustomFormatter(logging.Formatter):
    def format(self, record):
        if record.args != ():
            if isinstance(record.args, AccessLogAtoms):
                return super().format(record)
            argList = []
            for arg in record.args:
                if arg is None:
                    argList.append('')
                else:
                    argList.append(arg)
            fullMsg = record.msg % (tuple(argList))
        else:
            fullMsg = record.msg
        escapedMsg = fullMsg.replace('\\', '\\\\').replace('"', '\\"')
        record.msg = escapedMsg
        record.args = ()
        return super().format(record)
    
# create log folder if it doesn't exist
if not os.path.exists('Logs'):
    os.mkdir('Logs')

# create log handlers and assign custom formatter
parentDir = str(pathlib.Path(__file__).parent.absolute()).replace("\\",'/')
fileHandler = logging.FileHandler(filename = parentDir + '/Logs/HalloweenEventApi.log')
stdoutHandler = logging.StreamHandler(sys.stdout)
customFormatter = CustomFormatter('{"level":"%(levelname)s","time":"%(asctime)s","message":"%(message)s","name":"%(name)s"}')
fileHandler.setFormatter(customFormatter)
stdoutHandler.setFormatter(customFormatter)
handlers = [fileHandler, stdoutHandler]

# initialize logger
logging.basicConfig(handlers = handlers, 
                    level = logging.INFO)
logger = logging.getLogger()

# start property manager and get properties
APIPropertiesManager.startPropertyManager()
logger.setLevel(APIPropertiesManager.LOG_LEVEL)

# start firebase scheduler
FirebaseService.startFirebaseScheduler(APIPropertiesManager.FIREBASE_CONFIG_JSON)

# Flask REST API
app = Flask(__name__)
cors = CORS(app, resources={r"*": {"origins": "*"}})
api = Api(app)

# create event scheduler for shutdown
def shutDownApplication():
    try:
        queries.emailResults()
    except Exception:
        logging.error("Error emailing results.")
    os.system("kill -15 1")

sched = BackgroundScheduler(daemon=True)
sched.add_job(shutDownApplication, 'date', run_date = datetime.strptime(APIPropertiesManager.SCHEDULED_SHUTDOWN_TIME, "%m/%d/%y %I:%M:%S %p"))
sched.start()

class Scoreboard(Resource):
    def get(self):
        try:
            # get latest scoreboard history
            topScore = queries.getTopScore()
            scoreboard = queries.getScoreboard()
            return {"topScore": topScore, "scoreboard": scoreboard}
        except:
            abort(400, "Error getting latest scoreboard.")

class Fight(Resource):
    def post(self):
        value = request.get_data()

        try:
            errorMsg = "Invalid Request."
            value = json.loads(value)

            # validate there is a field for scannedUserKey (str) scannerUserKey (str) time (date)
            isInvalid = False

            dateTimeObj = datetime.now()
            time = dateTimeObj.strftime("%m/%d/%y %I:%M:%S %p")

            if "scannedUserKey" not in value or value["scannedUserKey"] == None or value["scannedUserKey"] == "" or type(value["scannedUserKey"]) != str:
                isInvalid = True
            if "scannerUserKey" not in value or value["scannerUserKey"] == None or value["scannerUserKey"] == "" or type(value["scannerUserKey"]) != str:
                isInvalid = True

            if isInvalid:
                raise Exception
            errorMsg = "No fight occured."
            fight = queries.performFight(value["scannedUserKey"], value["scannerUserKey"], time)
            return fight
        except:
            abort(400, errorMsg)

class Users(Resource):
    def post(self):
        value = request.get_data()

        try:
            errorMsg = "Invalid Request."
            value = json.loads(value)

            # validate there is a field for name (str) email (str)
            isInvalid = False

            if "name" not in value or value["name"] == None or value["name"] == "" or type(value["name"]) != str:
                isInvalid = True
            if "email" not in value or value["email"] == None or value["email"] == "" or type(value["email"]) != str:
                isInvalid = True

            if isInvalid:
                raise Exception
            errorMsg = "No user added."
            userKey = queries.addParticipant(value["name"], value["email"])
            return userKey
        except:
            abort(400, errorMsg)

class Login(Resource):
    def post(self):
        value = request.get_data()

        try:
            errorMsg = "Invalid Request."
            value = json.loads(value)

            # validate there is a field for email (str)
            isInvalid = False

            if "email" not in value or value["email"] == None or value["email"] == "" or type(value["email"]) != str:
                isInvalid = True

            if isInvalid:
                raise Exception
            errorMsg = "No user logged in."
            userKey = queries.getParticipantKey(value["email"])
            return userKey
        except:
            abort(400, errorMsg)

api.add_resource(Scoreboard, '/scoreboard/')
api.add_resource(Fight, '/fight/')
api.add_resource(Users, '/users/')
api.add_resource(Login, '/login/')
app.add_url_rule('/favicon.ico', view_func = lambda: send_from_directory(parentDir + '/src/common', 'favicon-pumpkin.ico'))
app.run(host='0.0.0.0',
        port=APIPropertiesManager.API_PORT,
        # TODO
        ssl_context=('/HalloweenEvent/server.crt', '/HalloweenEvent/server.key')
        )