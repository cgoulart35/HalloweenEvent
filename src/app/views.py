#region IMPORTS
import pathlib
import os
import logging
import sys
import json
import requests
import uuid
import cv2
import numpy
import base64
from datetime import datetime, timedelta
import secrets
from flask import Blueprint, session, request, render_template, redirect, url_for, flash, abort

from src.app.properties import WebAppPropertiesManager
from src.common.firebase import FirebaseService
from src.common.eventstate import eventIsOpen, getCurrentSeasonWindow
from src.common.security import constantTimeEquals, verifyTurnstile, escapeHtml
#endregion

views = Blueprint("views", __name__)

@views.app_context_processor
def injectVersion():
    # Expose the build-stamped VERSION to every template (footer build tag).
    return {"version": WebAppPropertiesManager.VERSION}

@views.before_request
def gateClosedAfterEvent():
    # Once The Long Night has ended, keep the app reachable but closed: serve the
    # "ended" page (with final standings) for every route instead of the game.
    # Static assets/favicon are served outside this blueprint, so the page still
    # renders with styling.
    if not eventIsOpen(*getCurrentSeasonWindow()):
        scoreboardHTML, topScore = buildScoreboard()
        return render_template("ended.html",
                               participateLoginStyle='style="display: none;"',
                               logoutFeedProfileStyle='style="display: none;"',
                               scoreboard=scoreboardHTML, topScore=topScore)

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

def createNewSession(session, userKey, encodedImage, displayName):
    global openSessions
    filename = "src/app/static/" + userKey + ".png"
    with open(filename, 'wb') as f:
        f.write(base64.decodebytes(encodedImage))
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

def getCsrfToken():
    if 'csrfToken' not in session:
        session['csrfToken'] = secrets.token_urlsafe(32)
    return session['csrfToken']

def csrfTokenValid():
    # Reject when the session has no token (so a blank-vs-blank compare can't pass) and
    # when the submitted token doesn't match it.
    sessionToken = session.get('csrfToken', '')
    return bool(sessionToken) and constantTimeEquals(request.form.get('csrfToken', ''), sessionToken)

def _apiHeaders():
    return {"X-API-Key": WebAppPropertiesManager.API_KEY}

def getScoreboard():
    try:
        response = requests.get(WebAppPropertiesManager.API_HOST + "/scoreboard/",
                                headers=_apiHeaders())
        # An error response (e.g. the API's own 400/401) is JSON without a "scoreboard"
        # key; return None so callers degrade to an empty board instead of KeyError-ing.
        # Matters for the off-season gate, which calls buildScoreboard() unguarded.
        if response.status_code >= 400:
            return None
        return response.json()
    except Exception as e:
        logger.error(e)
        return None

def humanizeTime(value):
    # Reformat a "MM/DD/YY HH:MM:SS AM/PM" stamp for display: un-pad the date and hour
    # and drop :00 seconds (e.g. "06/14/26 02:45:00 PM" -> "6/14/26 2:45 PM").
    try:
        parsed = datetime.strptime(value, "%m/%d/%y %I:%M:%S %p")
    except (ValueError, TypeError):
        return value
    datePart = f"{parsed.month}/{parsed.day}/{parsed.strftime('%y')}"
    hour = parsed.hour % 12 or 12
    timePart = f"{hour}:{parsed.minute:02d}"
    if parsed.second:
        timePart += f":{parsed.second:02d}"
    meridiem = "AM" if parsed.hour < 12 else "PM"
    return f"{datePart} {timePart} {meridiem}"

def matchCardHtml(winner, loser, time):
    # One scoreboard / fight result as a tidy two-row card (WON / LOST badge + name) so
    # long display names wrap cleanly instead of forming a ragged one-line sentence.
    return (
        '<div class="w3-cell-row"><div class="w3-cell w3-container">'
        '<div class="match">'
        f'<div class="match-row win"><span class="match-badge">WON</span><span class="match-name">{escapeHtml(winner)}</span></div>'
        f'<div class="match-row loss"><span class="match-badge">LOST</span><span class="match-name">{escapeHtml(loser)}</span></div>'
        '</div>'
        f'<div class="match-time">{escapeHtml(humanizeTime(time))}</div>'
        '</div></div>'
    )

def buildScoreboard():
    scoreboardJson = getScoreboard()
    scoreboardHTML = ""
    topScore = 0
    if scoreboardJson != None:
        for event in scoreboardJson["scoreboard"]:
            scoreboardHTML += matchCardHtml(event["winner"], event["loser"], event["time"]) + '<hr>'
        topScore = scoreboardJson["topScore"]
    return scoreboardHTML, topScore

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
        scoreboardHTML, topScore = buildScoreboard()
    except Exception:
        scoreboardHTML, topScore = "", 0

    return render_template("feed.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, scoreboard = scoreboardHTML, topScore = topScore)

@views.route("/scan/", methods = ["POST"])
def scan():
    if not sessionExists(session):
        return redirect(url_for("views.login"))
    try:
        file = request.files["file"].read()
        nparr = numpy.frombuffer(file, numpy.uint8)
        imageNp = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        detector = cv2.QRCodeDetector()
        decodedText, points, _ = detector.detectAndDecode(imageNp)
        if not decodedText:
            return ("Error scanning QR code.", 400)
        return (decodedText, 200)
    except Exception:
        return ("Error scanning QR code.", 400)

@views.route("/fight/")
def fight():
    if sessionExists(session):
        participateLoginStyle = "style=\"display: none;\""
        logoutFeedProfileStyle = ""
    else:
        return redirect(url_for("views.login"))
    
    args = request.args
    scannedUserKey = args.get('scannedUserKey')
    scannerUserKey = getSessionUserKey(session)

    fightResponse = None
    try:
        fightResponse = requests.post(WebAppPropertiesManager.API_HOST + "/fight/", headers=_apiHeaders(), data = json.dumps({"scannedUserKey": scannedUserKey, "scannerUserKey": scannerUserKey}))
        if fightResponse.status_code >= 400:
            raise Exception
        flash("Fight Complete", 'success')
        fight = fightResponse.json()
        if "winner" in fight and "loser" in fight and "time" in fight and "winnerKey" in fight and "loserKey" in fight:
            fightHTML = matchCardHtml(fight["winner"], fight["loser"], fight["time"]) + '<hr>'

            if fight["winnerKey"] == scannerUserKey and fight["loserKey"] == scannedUserKey:
                fightHTML += f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"youWon\" src=\"{url_for('static', filename='youWon.png')}\"></div></div><hr>"
                return render_template("youWon.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, fightHTML = fightHTML)
            else:
                fightHTML += f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"youDied\" src=\"{url_for('static', filename='youDied.png')}\"></div></div><hr>"
                return render_template("youLost.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, fightHTML = fightHTML)
    except:
        if fightResponse is None:
            flash("Could not reach the game server. Please try again.", 'error')
            return redirect(url_for("views.feed"))
        flash(fightResponse.json()["message"], 'error')
        if fightResponse.status_code == 403:
            fightHTML = f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"niceTry\" src=\"{url_for('static', filename='niceTry.png')}\"></div></div><hr>"
            return render_template("noFight.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, fightHTML = fightHTML)

    return redirect(url_for("views.feed"))

@views.route("/qrcode/")
def qrcode():
    if sessionExists(session):
        participateLoginStyle = "style=\"display: none;\""
        logoutFeedProfileStyle = ""
    else:
        return redirect(url_for("views.login"))

    qrcodeHTML = f"<div class=\"w3-cell-row\"><div class=\"w3-cell w3-container\"><img class=\"qrcode\" src=\"{url_for('static', filename=getSessionUserKey(session) + '.png')}\"></div></div><hr>"
    return render_template("qrcode.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, qrcodeHTML = qrcodeHTML)

@views.route("/profile/", methods = ["GET", "POST"])
def profile():
    if sessionExists(session):
        participateLoginStyle = "style=\"display: none;\""
        logoutFeedProfileStyle = ""
    else:
        return redirect(url_for("views.login"))
    if request.method == "POST":
        if not csrfTokenValid():
            abort(400)
        email = request.form['email']
        password = request.form['password']
        currentPassword = request.form.get('currentPassword', '')

        updateProfileResponse = None
        try:
            updateProfileResponse = requests.put(WebAppPropertiesManager.API_HOST + "/users/", headers=_apiHeaders(), data = json.dumps({"userKey": getSessionUserKey(session), "email": email, "currentPassword": currentPassword, "password": password}))
            password = None
            currentPassword = None
            if updateProfileResponse.status_code >= 400:
                raise Exception
            flash("Profile Updated", 'success')
        except:
            password = None
            currentPassword = None
            if updateProfileResponse is None:
                flash("Could not reach the game server. Please try again.", 'error')
            else:
                flash(updateProfileResponse.json()["message"], 'error')
        return redirect(url_for("views.profile"))

    return render_template("profile.html", participateLoginStyle = participateLoginStyle, logoutFeedProfileStyle = logoutFeedProfileStyle, displayName = getSessionUserName(session), csrfToken = getCsrfToken())

@views.route("/logout/")
def logout():
    if sessionExists(session):
        endSession(session)
        return redirect(url_for("views.login"))
    return ('', 204)

@views.route("/participate/", methods = ["GET", "POST"])
def participate():
    if sessionExists(session):
        return redirect(url_for("views.feed"))
    if request.method == "POST":
        if not csrfTokenValid():
            abort(400)
        if not verifyTurnstile(WebAppPropertiesManager.TURNSTILE_SECRET_KEY,
                               request.form.get('cf-turnstile-response'),
                               request.remote_addr):
            flash("CAPTCHA verification failed. Please try again.", 'error')
            return render_template("participate.html", participateLoginStyle = "", logoutFeedProfileStyle = "style=\"display: none;\"", shutdownTime = humanizeTime(getCurrentSeasonWindow()[1]), csrfToken = getCsrfToken(), turnstileSiteKey = WebAppPropertiesManager.TURNSTILE_SITE_KEY)
        email = request.form['email']
        password = request.form['password']
        name = request.form['name']

        createUserResponse = None
        try:
            createUserResponse = requests.post(WebAppPropertiesManager.API_HOST + "/users/", headers=_apiHeaders(), data = json.dumps({"email": email, "password": password, "name": name}))
            password = None
            if createUserResponse.status_code >= 400:
                raise Exception
            userKey = createUserResponse.json()["userKey"]
            encodedImage = createUserResponse.json()["qrcode"]
            displayName = createUserResponse.json()["displayName"]
            flash("Logged in as " + displayName, 'success')
            createNewSession(session, userKey, encodedImage.encode(), displayName)
            return redirect(url_for("views.feed"))
        except:
            password = None
            if createUserResponse is None:
                flash("Could not reach the game server. Please try again.", 'error')
            else:
                flash(createUserResponse.json()["message"], 'error')

    return render_template("participate.html", participateLoginStyle = "", logoutFeedProfileStyle = "style=\"display: none;\"", shutdownTime = humanizeTime(getCurrentSeasonWindow()[1]), csrfToken = getCsrfToken(), turnstileSiteKey = WebAppPropertiesManager.TURNSTILE_SITE_KEY)

@views.route("/login/", methods = ["GET", "POST"])
def login():
    if sessionExists(session):
        return redirect(url_for("views.feed"))
    if request.method == "POST":
        if not csrfTokenValid():
            abort(400)
        if not verifyTurnstile(WebAppPropertiesManager.TURNSTILE_SECRET_KEY,
                               request.form.get('cf-turnstile-response'),
                               request.remote_addr):
            flash("CAPTCHA verification failed. Please try again.", 'error')
            return render_template("login.html", participateLoginStyle = "", logoutFeedProfileStyle = "style=\"display: none;\"", csrfToken = getCsrfToken(), turnstileSiteKey = WebAppPropertiesManager.TURNSTILE_SITE_KEY)
        email = request.form['email']
        password = request.form['password']

        loginResponse = None
        try:
            loginResponse = requests.post(WebAppPropertiesManager.API_HOST + "/login/", headers=_apiHeaders(), data = json.dumps({"email": email, "password": password}))
            password = None
            if loginResponse.status_code >= 400:
                raise Exception
            userKey = loginResponse.json()["userKey"]
            encodedImage = loginResponse.json()["qrcode"]
            displayName = loginResponse.json()["displayName"]
            flash("Logged in as " + displayName, 'success')
            createNewSession(session, userKey, encodedImage.encode(), displayName)
            return redirect(url_for("views.feed"))
        except:
            password = None
            if loginResponse is None:
                flash("Could not reach the game server. Please try again.", 'error')
            else:
                flash(loginResponse.json()["message"], 'error')

    return render_template("login.html", participateLoginStyle = "", logoutFeedProfileStyle = "style=\"display: none;\"", csrfToken = getCsrfToken(), turnstileSiteKey = WebAppPropertiesManager.TURNSTILE_SITE_KEY)