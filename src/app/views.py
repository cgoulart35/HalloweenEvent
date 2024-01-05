#region IMPORTS
import pathlib
import os
import logging
import sys
import json
import requests
from hypercorn.logging import AccessLogAtoms
from flask import Blueprint, session, render_template, request, redirect, url_for

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

cachedScoreboard = None
def getScoreboard():
    global cachedScoreboard
    # TODO
    try:
        response = requests.get(WebAppPropertiesManager.API_HOST + "/scoreboard/",
                                verify=False)
        cachedScoreboard = response.json()
    except Exception as e:
        logger.error(e)

@views.route("/")
def root():
    if "userKey" in session:
        return redirect(url_for("views.feed"))
    else:
        return redirect(url_for("views.participate"))

@views.route("/feed/")
def feed():
    if "userKey" in session:
        participateLoginStyle = "style=\"display: none;\""
        logoutFeedStyle = ""
    else:
        return redirect(url_for("views.login"))
    try:
        global cachedScoreboard
        scoreboardHTML = ""
        topScore = 0

        if cachedScoreboard != None:
            for event in cachedScoreboard["scoreboard"]:
                scoreboardHTML += f'<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><h3>{event["winner"]} defeated {event["loser"]}.</h3><h5>Time: {event["time"]}</h5></div></div><hr>'

            topScore = cachedScoreboard["topScore"]

        return render_template("feed.html", participateLoginStyle = participateLoginStyle, logoutFeedStyle = logoutFeedStyle, scoreboard = scoreboardHTML, topScore = topScore)
    except Exception:
        pass;  

    return render_template("feed.html", participateLoginStyle = participateLoginStyle, logoutFeedStyle = logoutFeedStyle, scoreboard = "")

@views.route("/fight/", methods = ["GET", "POST"])
def fight():
    if "userKey" in session:
        participateLoginStyle = "style=\"display: none;\""
        logoutFeedStyle = ""
    else:
        return redirect(url_for("views.login"))
    
    args = request.args
    scannedUserKey = args.get('scannedUserKey')
    scannerUserKey = session['userKey']

    if scannedUserKey != scannerUserKey:
        try:
            response = requests.post(WebAppPropertiesManager.API_HOST + "/fight/", data = json.dumps({"scannedUserKey": scannedUserKey, "scannerUserKey": scannerUserKey}))
            fight = response.json()
            if fight == False:
                fightHTML = f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"niceTry\" src=\"{url_for('static', filename='niceTry.png')}\"></div></div><hr>"
                return render_template("noFight.html", participateLoginStyle = participateLoginStyle, logoutFeedStyle = logoutFeedStyle, fightHTML = fightHTML)
            if "winner" in fight and "loser" in fight and "time" in fight and "winnerKey" in fight and "loserKey" in fight:
                fightHTML = f'<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><h3>{fight["winner"]} defeated {fight["loser"]}.</h3><h5>Time: {fight["time"]}</h5></div></div><hr>'

                if fight["winnerKey"] == scannerUserKey and fight["loserKey"] == scannedUserKey:
                    fightHTML += f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"youWon\" src=\"{url_for('static', filename='youWon.png')}\"></div></div><hr>"
                    return render_template("youWon.html", participateLoginStyle = participateLoginStyle, logoutFeedStyle = logoutFeedStyle, fightHTML = fightHTML)
                else:
                    fightHTML += f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"youDied\" src=\"{url_for('static', filename='youDied.png')}\"></div></div><hr>"
                    return render_template("youLost.html", participateLoginStyle = participateLoginStyle, logoutFeedStyle = logoutFeedStyle, fightHTML = fightHTML)
        except:
            pass

    return redirect(url_for("views.feed"))

@views.route("/participate/", methods = ["GET", "POST"])
def participate():
    if "userKey" in session:
        return redirect(url_for("views.feed"))
    if request.method == "POST":
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']

        try:
            userKey = requests.post(WebAppPropertiesManager.API_HOST + "/users/", data = json.dumps({"email": email, "password": password, "name": name}))
            password = None
            if userKey.status_code == 400:
                raise Exception
            session['userKey'] = userKey.json()
            return redirect(url_for("views.feed"))
        except:
            password = None
            pass

    return render_template("participate.html", participateLoginStyle = "", logoutFeedStyle = "style=\"display: none;\"", shutdownTime = WebAppPropertiesManager.SCHEDULED_SHUTDOWN_TIME)

@views.route("/login/", methods = ["GET", "POST"])
def login():
    if "userKey" in session:
        return redirect(url_for("views.feed"))
    if request.method == "POST":
        email = request.form['email']
        password = request.form['password']

        try:
            userKey = requests.post(WebAppPropertiesManager.API_HOST + "/login/", data = json.dumps({"email": email, "password": password}))
            password = None
            if userKey.status_code == 400:
                raise Exception
            session['userKey'] = userKey.json()
            return redirect(url_for("views.feed"))
        except:
            password = None
            pass

    return render_template("login.html", participateLoginStyle = "", logoutFeedStyle = "style=\"display: none;\"")

@views.route("/logout/")
def logout():
    if "userKey" in session:
        session.pop("userKey", None)
    return redirect(url_for("views.login"))