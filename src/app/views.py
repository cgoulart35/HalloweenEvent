#region IMPORTS
import pathlib
import os
import logging
import sys
import json
import requests
import uuid
from datetime import datetime, timedelta
from hypercorn.logging import AccessLogAtoms
from flask import Blueprint, session, request, render_template, redirect, url_for, flash

from src.app.properties import WebAppPropertiesManager
from src.common.firebase import FirebaseService
#endregion

views = Blueprint("views", __name__)

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
parentDir = str(pathlib.Path(__file__).parent.parent.parent.absolute()).replace("\\",'/')
fileHandler = logging.FileHandler(filename = parentDir + '/Logs/HalloweenEventWebApp.log')
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
WebAppPropertiesManager.startPropertyManager()
logger.setLevel(WebAppPropertiesManager.LOG_LEVEL)

# start firebase scheduler
FirebaseService.startFirebaseScheduler(WebAppPropertiesManager.FIREBASE_CONFIG_JSON)

openSessions = dict()
def expireServerSessions():
    currentTime = datetime.now()
    expiredSessionIds = []
    for sessionId, session in openSessions.items():
        createdTime = session["created"]
        if (currentTime - createdTime >= timedelta(days = 1)):
            expiredSessionIds.append(sessionId)
    for sessionId in expiredSessionIds:
        openSessions.pop(sessionId)

def createNewSession(session, userKey, displayName):
    global openSessions
    newSessionId = str(uuid.uuid4())
    openSessions[newSessionId] = {"userKey": userKey, "displayName": displayName, "created": datetime.now()}
    session["sessionId"] = newSessionId

def endSession(session):
    global openSessions
    if "sessionId" in session:
        openSessions.pop(session["sessionId"])
        session.pop("sessionId", None)

def sessionExists(session):
    global openSessions
    if "sessionId" not in session:
        return False
    return session["sessionId"] in openSessions

def getSessionUserKey(session):
    global openSessions
    return openSessions[session["sessionId"]]["userKey"]

def getSessionUserName(session):
    global openSessions
    return openSessions[session["sessionId"]]["displayName"]

def getScoreboard():
    # TODO
    try:
        response = requests.get(WebAppPropertiesManager.API_HOST + "/scoreboard/",
                                verify=False)
        return response.json()
    except Exception as e:
        logger.error(e)
        return None

@views.route("/", defaults = {"path": ""})
@views.route("/<path:path>")
def root(path):
    if sessionExists(session):
        return redirect(url_for("views.feed"))
    else:
        return redirect(url_for("views.participate"))

@views.route("/feed/")
def feed():
    if sessionExists(session):
        participateLoginStyle = "style=\"display: none;\""
        logoutFeedProfileStyle = ""
    else:
        return redirect(url_for("views.login"))
    try:
        scoreboardJson = getScoreboard()
        scoreboardHTML = ""
        topScore = 0

        if scoreboardJson != None:
            for event in scoreboardJson["scoreboard"]:
                scoreboardHTML += f'<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><h3>{event["winner"]} defeated {event["loser"]}.</h3><h5>Time: {event["time"]}</h5></div></div><hr>'

            topScore = scoreboardJson["topScore"]

        return render_template("feed.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, scoreboard = scoreboardHTML, topScore = topScore)
    except Exception:
        pass;  

    return render_template("feed.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, scoreboard = "")

@views.route("/profile/", methods = ["GET", "POST"])
def profile():
    if sessionExists(session):
        participateLoginStyle = "style=\"display: none;\""
        logoutFeedProfileStyle = ""
    else:
        return redirect(url_for("views.login"))
    if request.method == "POST":
        email = request.form['email']
        password = request.form['password']

        try:
            updateProfileResponse = requests.put(WebAppPropertiesManager.API_HOST + "/users/", data = json.dumps({"userKey": getSessionUserKey(session), "email": email, "password": password}))
            password = None
            if updateProfileResponse.status_code == 400:
                raise Exception
            flash("Profile Updated", 'success')
        except:
            password = None
            flash(updateProfileResponse.json()["message"], 'error')

    return render_template("profile.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, displayName = getSessionUserName(session))

@views.route("/fight/", methods = ["GET", "POST"])
def fight():
    if sessionExists(session):
        participateLoginStyle = "style=\"display: none;\""
        logoutFeedProfileStyle = ""
    else:
        return redirect(url_for("views.login"))
    
    args = request.args
    scannedUserKey = args.get('scannedUserKey')
    scannerUserKey = getSessionUserKey(session)

    try:
        fightResponse = requests.post(WebAppPropertiesManager.API_HOST + "/fight/", data = json.dumps({"scannedUserKey": scannedUserKey, "scannerUserKey": scannerUserKey}))
        if fightResponse.status_code >= 400:
            raise Exception
        flash("Fight Complete", 'success')
        fight = fightResponse.json()
        if "winner" in fight and "loser" in fight and "time" in fight and "winnerKey" in fight and "loserKey" in fight:
            fightHTML = f'<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><h3>{fight["winner"]} defeated {fight["loser"]}.</h3><h5>Time: {fight["time"]}</h5></div></div><hr>'

            if fight["winnerKey"] == scannerUserKey and fight["loserKey"] == scannedUserKey:
                fightHTML += f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"youWon\" src=\"{url_for('static', filename='youWon.png')}\"></div></div><hr>"
                return render_template("youWon.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, fightHTML = fightHTML)
            else:
                fightHTML += f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"youDied\" src=\"{url_for('static', filename='youDied.png')}\"></div></div><hr>"
                return render_template("youLost.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, fightHTML = fightHTML)
    except:
        flash(fightResponse.json()["message"], 'error')
        if fightResponse.status_code == 403:
            fightHTML = f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"niceTry\" src=\"{url_for('static', filename='niceTry.png')}\"></div></div><hr>"
            return render_template("noFight.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, fightHTML = fightHTML)

    return redirect(url_for("views.feed"))

@views.route("/participate/", methods = ["GET", "POST"])
def participate():
    if sessionExists(session):
        return redirect(url_for("views.feed"))
    if request.method == "POST":
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']

        try:
            createUserResponse = requests.post(WebAppPropertiesManager.API_HOST + "/users/", data = json.dumps({"email": email, "password": password, "name": name}))
            password = None
            if createUserResponse.status_code == 400:
                raise Exception
            userKey = createUserResponse.json()["userKey"]
            displayName = createUserResponse.json()["displayName"]
            flash("Logged in as " + displayName, 'success')
            createNewSession(session, userKey, displayName)
            return redirect(url_for("views.feed"))
        except:
            password = None
            flash(createUserResponse.json()["message"], 'error')

    return render_template("participate.html", participateLoginStyle = "", logoutFeedProfileStyle = "style=\"display: none;\"", shutdownTime = WebAppPropertiesManager.SCHEDULED_SHUTDOWN_TIME)

@views.route("/login/", methods = ["GET", "POST"])
def login():
    if sessionExists(session):
        return redirect(url_for("views.feed"))
    if request.method == "POST":
        email = request.form['email']
        password = request.form['password']

        try:
            loginResponse = requests.post(WebAppPropertiesManager.API_HOST + "/login/", data = json.dumps({"email": email, "password": password}))
            password = None
            if loginResponse.status_code == 400:
                raise Exception
            userKey = loginResponse.json()["userKey"]
            displayName = loginResponse.json()["displayName"]
            flash("Logged in as " + displayName, 'success')
            createNewSession(session, userKey, displayName)
            return redirect(url_for("views.feed"))
        except:
            password = None
            flash(loginResponse.json()["message"], 'error')

    return render_template("login.html", participateLoginStyle = "", logoutFeedProfileStyle = "style=\"display: none;\"")

@views.route("/logout/")
def logout():
    if sessionExists(session):
        endSession(session)
        return redirect(url_for("views.login"))
    return ('', 204)