#region IMPORTS
import pathlib
import os
import logging
import sys
import json
import bcrypt
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, abort, send_from_directory, request
from flask_restful import Api, Resource
from flask_cors import CORS

from src.common import queries
from src.common import lifecycle
from src.api.properties import APIPropertiesManager
from src.common.firebase import FirebaseService
from src.common.eventstate import eventIsOpen, getCurrentSeasonWindow
from src.common.exceptions import NoParticipantFound, EmailInUse, NotAllowedToFightSelf, NotAllowedToFightAgain, IncorrectPassword
from src.common.security import constantTimeEquals
#endregion

class CustomFormatter(logging.Formatter):
    def format(self, record):
        if record.args != ():
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
parentDir = str(pathlib.Path(__file__).parent.parent.parent.absolute()).replace("\\",'/')
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
cors = CORS(app, resources={r"*": {"origins": [APIPropertiesManager.WEBAPP_HOST]}})
api = Api(app)

@app.before_request
def requireApiKey():
    if request.method == "OPTIONS" or request.path == "/favicon.ico":
        return
    key = request.headers.get("X-API-Key", "")
    if not constantTimeEquals(key, APIPropertiesManager.API_KEY):
        abort(401, "Unauthorized.")

# Seed the season metadata if missing (non-destructive), then run the lifecycle
# reconcile loop on an interval. The loop is the single driver of the yearly cycle:
# at season close it emails final results; at the next season open (Oct 1) it archives
# the finished season to halloween-event-{year}, opens a fresh one, and emails past
# players. It's idempotent and self-heals across container restarts (nothing depends on
# hitting an exact instant). next_run_time fires it once immediately on boot for catch-up.
lifecycle.ensureProvisioned()

sched = BackgroundScheduler(daemon=True)
sched.add_job(lifecycle.reconcileEventLifecycle, 'interval', minutes = 5,
              max_instances = 1, coalesce = True, next_run_time = datetime.now())
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
        if not eventIsOpen(*getCurrentSeasonWindow()):
            abort(403, "The Long Night is closed.")
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
        except Exception as e:
            errorCode = 400
            if isinstance(e, NotAllowedToFightSelf):
                errorMsg = "You are not allowed to fight yourself."
                errorCode = 403
            elif isinstance(e, NotAllowedToFightAgain):
                errorMsg = "You are not allowed to fight again."
                errorCode = 403
            abort(errorCode, errorMsg)

class Users(Resource):
    def post(self):
        if not eventIsOpen(*getCurrentSeasonWindow()):
            abort(403, "The Long Night is closed.")
        value = request.get_data()

        try:
            errorMsg = "Invalid Request."
            value = json.loads(value)

            # validate there is a field for name (str) email (str) password (str)
            isInvalid = False

            if "name" not in value or value["name"] == None or value["name"] == "" or type(value["name"]) != str:
                isInvalid = True
            if "email" not in value or value["email"] == None or value["email"] == "" or type(value["email"]) != str:
                isInvalid = True
            if "password" not in value or value["password"] == None or value["password"] == "" or type(value["password"]) != str:
                isInvalid = True

            if isInvalid:
                raise Exception
            
            # use bcrypt hash alogrithm and delete password in memory
            bytes = value["password"].encode('utf-8')
            salt = bcrypt.gensalt()
            hashedPassword = bcrypt.hashpw(bytes, salt)
            bytes = None
            value["password"] = None

            errorMsg = "No user added."
            addedParticipant = queries.addParticipant(value["name"], value["email"], hashedPassword.decode('utf-8'))
            return {"userKey": addedParticipant[0], "qrcode": addedParticipant[1], "displayName": value["name"]}
        except Exception as e:
            bytes = None
            if isinstance(value, dict):
                value["password"] = None
            if isinstance(e, EmailInUse):
                errorMsg = "Email already in use."
            abort(400, errorMsg)

    def put(self):
        value = request.get_data()

        try:
            errorMsg = "Invalid Request."
            value = json.loads(value)

            # validate there is a field for userKey (str) email (str) password (str)
            isInvalid = False
            isEmailInvalid = False
            isPasswordInvalid = False

            if "userKey" not in value or value["userKey"] == None or value["userKey"] == "" or type(value["userKey"]) != str:
                isInvalid = True
            if "email" not in value or value["email"] == None or value["email"] == "" or type(value["email"]) != str:
                isEmailInvalid = True
            if "password" not in value or value["password"] == None or value["password"] == "" or type(value["password"]) != str:
                isPasswordInvalid = True
            if isEmailInvalid and isPasswordInvalid:
                isInvalid = True

            if isInvalid:
                raise Exception

            userData = queries.getParticipantDataViaUserKey(value["userKey"])

            # verify current password before allowing any credential change. Raise (don't abort)
            # here: abort() inside this try would be caught by the except below and remapped to 400.
            currentPassword = value.get("currentPassword")
            if not currentPassword or type(currentPassword) != str:
                raise IncorrectPassword
            if not bcrypt.checkpw(currentPassword.encode('utf-8'), userData["hashedPassword"].encode('utf-8')):
                raise IncorrectPassword

            # fill in email if we are only updating password, else validate new email not in use
            if isEmailInvalid:
                value["email"] = userData["email"]
            elif value["email"] != userData["email"]:
                try:
                    queries.getParticipantDataViaEmail(value["email"])
                    raise EmailInUse
                except NoParticipantFound:
                    pass

            # use bcrypt alogrithm to check if password updated and delete password in memory
            hashedPassword = userData["hashedPassword"].encode('utf-8')
            # password may be absent here (email-only update is allowed), so don't index it
            # directly -- it's only actually used when isPasswordInvalid is False.
            bytes = (value.get("password") or "").encode('utf-8')
            if not isPasswordInvalid and not bcrypt.checkpw(bytes, hashedPassword):
                salt = bcrypt.gensalt()
                hashedPassword = bcrypt.hashpw(bytes, salt)
            bytes = None
            value["password"] = None
            value["currentPassword"] = None

            errorMsg = "No user updated."
            queries.updateParticipant(value["userKey"], value["email"], hashedPassword.decode('utf-8'))
            return {"userKey": value["userKey"], "email": value["email"]}
        except Exception as e:
            bytes = None
            if isinstance(value, dict):
                value["password"] = None
                value["currentPassword"] = None
            if isinstance(e, IncorrectPassword):
                abort(403, "Current password is incorrect.")
            if isinstance(e, EmailInUse):
                errorMsg = "Email already in use."
            abort(400, errorMsg)

class Login(Resource):
    def post(self):
        value = request.get_data()

        try:
            errorMsg = "Invalid Request."
            value = json.loads(value)

            # validate there is a field for email (str) password (str)
            isInvalid = False

            if "email" not in value or value["email"] == None or value["email"] == "" or type(value["email"]) != str:
                isInvalid = True
            if "password" not in value or value["password"] == None or value["password"] == "" or type(value["password"]) != str:
                isInvalid = True

            if isInvalid:
                raise Exception

            errorMsg = "Incorrect email or password."
            userData = queries.getParticipantDataViaEmail(value["email"])

            # use bcrypt alogrithm to check password and delete password in memory
            hashedPassword = userData[1]["hashedPassword"].encode('utf-8')
            bytes = value["password"].encode('utf-8')
            if not bcrypt.checkpw(bytes, hashedPassword):
                raise Exception
            bytes = None
            value["password"] = None
            
            return {"userKey": userData[0], "qrcode": userData[1]["qrcode"], "displayName": userData[1]["name"]}
        except:
            bytes = None
            if isinstance(value, dict):
                value["password"] = None
            abort(400, errorMsg)

class Reminders(Resource):
    def post(self):
        # Opt in to ("remind me on Oct 1") or out of (unsubscribe) the season-start email.
        # Deliberately NOT gated by eventIsOpen: opt-in happens off-season (that's the whole
        # point) and unsubscribe must work at any time. The shared X-API-Key gate (above)
        # still applies, so only the web app can reach it.
        value = request.get_data()
        try:
            value = json.loads(value)
            email = value.get("email")
            action = value.get("action")
            if not email or type(email) != str or action not in ("subscribe", "unsubscribe"):
                raise Exception
            queries.setReminderSubscription(email, action == "subscribe")
            return {"email": email, "status": action}
        except Exception:
            abort(400, "Invalid Request.")

api.add_resource(Scoreboard, '/scoreboard/')
api.add_resource(Fight, '/fight/')
api.add_resource(Users, '/users/')
api.add_resource(Login, '/login/')
api.add_resource(Reminders, '/reminders/')
app.add_url_rule('/favicon.ico', view_func = lambda: send_from_directory(parentDir + '/src/common', 'favicon-pumpkin.ico'))
# HTTP only: the API runs behind the Cloudflare tunnel and is reached by the web app
# over the LAN (API_HOST). TLS terminates at the tunnel, so no ssl_context here.
app.run(host='0.0.0.0',
        port=APIPropertiesManager.API_PORT)