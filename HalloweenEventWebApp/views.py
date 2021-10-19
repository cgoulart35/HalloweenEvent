import json
import importlib.util
import pathlib
import requests
from configparser import ConfigParser
from flask import Blueprint, session, render_template, request, redirect, url_for

views = Blueprint(__name__, "views")

# get parent directory and dependencies
parentDir = str(pathlib.Path(__file__).parent.parent.absolute())
parentDir = parentDir.replace("\\",'/')

spec = importlib.util.spec_from_file_location('shared', parentDir + '/Shared/functions.py')
functions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(functions)

# get configuration variables
appConfig = ConfigParser()
appConfig.read('HalloweenEventWebApp/app.ini')
sharedConfig = functions.buildSharedConfig(parentDir)

shutdownTime = sharedConfig['properties']['scheduledShutdownTime']
firebaseConfigJson = sharedConfig['properties']['firebaseConfigJson']
firebaseAuthEmail = sharedConfig['properties']['firebaseAuthEmail']
firebaseAuthPassword = sharedConfig['properties']['firebaseAuthPassword']
apiHost = appConfig['properties']['apiHost']
secretKey = appConfig['properties']['secretKey']

# initialize firebase and database
firebase = functions.buildFirebase(firebaseConfigJson)
db = firebase.database()
auth = firebase.auth()

cachedScoreboard = None
def getScoreboard():
    global cachedScoreboard
    response = requests.get(apiHost+ "/HalloweenEvent/Scoreboard/")
    cachedScoreboard = response.json()

@views.route("/")
@views.route("/Scoreboard/")
def scoreboard():
    if "userKey" in session:
        participateLoginStyle = "style=\"display: none;\""
        logoutStyle = ""
    else:
        participateLoginStyle = ""
        logoutStyle = "style=\"display: none;\""
    try:
        global cachedScoreboard
        scoreboardHTML = ""
        topScore = 0

        if cachedScoreboard != None:
            for event in cachedScoreboard["scoreboard"]:
                scoreboardHTML += f'<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><h3>{event["winner"]} defeated {event["loser"]}.</h3><h5>Time: {event["time"]}</h5></div></div><hr>'

            topScore = cachedScoreboard["topScore"]

        return render_template("scoreboard.html", participateLoginStyle = participateLoginStyle, logoutStyle = logoutStyle, scoreboard = scoreboardHTML, topScore = topScore)
    except Exception:
        pass;  

    return render_template("scoreboard.html", participateLoginStyle = participateLoginStyle, logoutStyle = logoutStyle, scoreboard = "")

@views.route("/Fight/", methods = ["GET", "POST"])
def fight():
    if "userKey" in session:
        participateLoginStyle = "style=\"display: none;\""
        logoutStyle = ""
    else:
        return redirect(url_for("views.login"))
    
    args = request.args
    scannedUserKey = args.get('scannedUserKey')
    scannerUserKey = session['userKey']

    if scannedUserKey != scannerUserKey:
        try:
            response = requests.post(apiHost + "/HalloweenEvent/Fight/", data = json.dumps({"scannedUserKey": scannedUserKey, "scannerUserKey": scannerUserKey}))
            fight = response.json()
            if fight == False:
                fightHTML = f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"niceTry\" src=\"{url_for('static', filename='niceTry.png')}\"></div></div><hr>"
                return render_template("noFight.html", participateLoginStyle = participateLoginStyle, logoutStyle = logoutStyle, fightHTML = fightHTML)
            if "winner" in fight and "loser" in fight and "time" in fight and "winnerKey" in fight and "loserKey" in fight:
                fightHTML = f'<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><h3>{fight["winner"]} defeated {fight["loser"]}.</h3><h5>Time: {fight["time"]}</h5></div></div><hr>'

                if fight["winnerKey"] == scannerUserKey and fight["loserKey"] == scannedUserKey:
                    fightHTML += f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"youWon\" src=\"{url_for('static', filename='youWon.png')}\"></div></div><hr>"
                    return render_template("youWon.html", participateLoginStyle = participateLoginStyle, logoutStyle = logoutStyle, fightHTML = fightHTML)
                else:
                    fightHTML += f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"youDied\" src=\"{url_for('static', filename='youDied.png')}\"></div></div><hr>"
                    return render_template("youLost.html", participateLoginStyle = participateLoginStyle, logoutStyle = logoutStyle, fightHTML = fightHTML)
        except:
            pass

    return redirect(url_for("views.scoreboard"))

@views.route("/Participate/", methods = ["GET", "POST"])
def participate():
    if "userKey" in session:
        return redirect(url_for("views.scoreboard"))
    if request.method == "POST":
        email = request.form['email']
        name = request.form['name']

        try:
            userKey = requests.post(apiHost + "/HalloweenEvent/Users/", data = json.dumps({"email": email, "name": name}))
            if userKey.status_code == 400:
                raise Exception
            session['userKey'] = userKey.json()
            return redirect(url_for("views.scoreboard"))
        except:
            pass

    return render_template("participate.html", participateLoginStyle = "", logoutStyle = "style=\"display: none;\"", shutdownTime = shutdownTime)

@views.route("/Login/", methods = ["GET", "POST"])
def login():
    if "userKey" in session:
        return redirect(url_for("views.scoreboard"))
    if request.method == "POST":
        email = request.form['email']

        try:
            userKey = requests.post(apiHost + "/HalloweenEvent/Login/", data = json.dumps({"email": email}))
            if userKey.status_code == 400:
                raise Exception
            session['userKey'] = userKey.json()
            return redirect(url_for("views.scoreboard"))
        except:
            pass

    return render_template("login.html", participateLoginStyle = "", logoutStyle = "style=\"display: none;\"")

@views.route("/Logout/")
def logout():
    if "userKey" in session:
        session.pop("userKey", None)
    return redirect(url_for("views.login"))