#region IMPORTS
import json
import logging
import importlib.util
import pathlib
import os
from datetime import datetime
from configparser import ConfigParser
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, abort, request
from flask_restful import Api, Resource
from flask_cors import CORS
#endregion

# get parent directory and dependencies
parentDir = str(pathlib.Path(__file__).parent.parent.absolute())
parentDir = parentDir.replace("\\",'/')

spec = importlib.util.spec_from_file_location('shared', parentDir + '/Shared/functions.py')
functions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(functions)

spec = importlib.util.spec_from_file_location('shared', parentDir + '/Shared/queries.py')
queries = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queries)

# get configuration variables
apiConfig = ConfigParser()
apiConfig.read('HalloweenEventApi/api.ini')
sharedConfig = functions.buildSharedConfig(parentDir)

shutdownTime = sharedConfig['properties']['scheduledShutdownTime']
firebaseConfigJson = sharedConfig['properties']['firebaseConfigJson']
firebaseAuthEmail = sharedConfig['properties']['firebaseAuthEmail']
firebaseAuthPassword = sharedConfig['properties']['firebaseAuthPassword']
webAppHost = apiConfig['properties']['webAppHost']
emailHost = apiConfig['properties']['emailHost']
emailPort = apiConfig['properties']['emailPort']
emailSender = apiConfig['properties']['emailSender']
emailPassword = apiConfig['properties']['emailPassword']

# create and configure logger
if not os.path.exists('Logs'):
    os.mkdir('Logs')
LOG_FORMAT = "%(levelname)s %(asctime)s - %(message)s"
logging.basicConfig(filename = parentDir + '/Logs/HalloweenEventApi.log', level = logging.INFO, format = LOG_FORMAT)

# initialize firebase and database
firebase = functions.buildFirebase(firebaseConfigJson)
db = firebase.database()
auth = firebase.auth()
user = auth.sign_in_with_email_and_password(firebaseAuthEmail, firebaseAuthPassword)

# Flask REST API
app = Flask(__name__)
cors = CORS(app, resources={r"*": {"origins": "*"}})
api = Api(app)

# create event scheduler for refreshing auth token and shutdown
def refreshToken():
    global user
    user = auth.refresh(user['refreshToken'])

def shutDownApplication():
    try:
        queries.emailResults(db, user['idToken'], emailHost, emailPort, emailSender, emailPassword)
    except Exception:
        logging.error("Error emailing results.")
    os.system(parentDir + "/stop.sh")

sched = BackgroundScheduler(daemon=True)
sched.add_job(refreshToken, 'interval', minutes = 30)
sched.add_job(shutDownApplication, 'date', run_date = datetime.strptime(shutdownTime, "%m/%d/%y %I:%M:%S %p"))
sched.start()

class Scoreboard(Resource):
    def get(self):
        try:
            # get latest scoreboard history
            topScore = queries.getTopScore(db, user['idToken'])
            scoreboard = queries.getScoreboard(db, user['idToken'])
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
            fight = queries.performFight(db, user['idToken'], value["scannedUserKey"], value["scannerUserKey"], time)
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
            userKey = queries.addParticipant(db, user['idToken'], shutdownTime, webAppHost, emailHost, emailPort, emailSender, emailPassword, value["name"], value["email"])
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
            userKey = queries.getParticipantKey(db, user['idToken'], value["email"])
            return userKey
        except:
            abort(400, errorMsg)

api.add_resource(Scoreboard, '/HalloweenEvent/Scoreboard/')
api.add_resource(Fight, '/HalloweenEvent/Fight/')
api.add_resource(Users, '/HalloweenEvent/Users/')
api.add_resource(Login, '/HalloweenEvent/Login/')
app.add_url_rule('/favicon.ico', view_func = lambda: functions.favicon(parentDir))
app.run(host='0.0.0.0', port=5003)