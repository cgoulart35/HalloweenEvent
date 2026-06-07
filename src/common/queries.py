#region IMPORTS
import qrcode
import random
import smtplib
import os
import base64
from io import BytesIO
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

from src.api.properties import APIPropertiesManager
from src.common.firebase import FirebaseService
from src.common.eventstate import EVENT_ROOT, getCurrentSeasonWindow
from src.common.exceptions import NoParticipantFound, EmailInUse, NotAllowedToFightSelf, NotAllowedToFightAgain
from src.common.security import escapeHtml
#endregion

def getScoreboard():
    result = FirebaseService.get([EVENT_ROOT, "scoreboard"])
    if result.val() != None:
        scoreboard = result.val()
        if isinstance(scoreboard, dict):
            return sorted(scoreboard.values(), key=lambda event: datetime.strptime(event["time"], "%m/%d/%y %I:%M:%S %p"), reverse=True)
        else:
            return sorted(scoreboard, key=lambda event: datetime.strptime(event["time"], "%m/%d/%y %I:%M:%S %p"), reverse=True)
    else:
        return []

def getTopScore():
    result = FirebaseService.get([EVENT_ROOT, "users"])
    if result.val() != None:
        users = result.val()
        if isinstance(users, dict):
            users = users.values()

        topScore = 0
        for user in users:
            if user["score"] > topScore:
                topScore = user["score"]

        return topScore
    else:
        return 0

def performFight(scannedUserKey, scannerUserKey, time):
    if scannedUserKey == scannerUserKey:
        raise NotAllowedToFightSelf

    scoreboard = getScoreboard()
    if scoreboard != []:    
        for event in scoreboard:
            if (event["winnerKey"] == scannedUserKey and event["loserKey"] == scannerUserKey) or event["winnerKey"] == scannerUserKey and event["loserKey"] == scannedUserKey:
                raise NotAllowedToFightAgain

    scannedUserResult = FirebaseService.get([EVENT_ROOT, "users", scannedUserKey])
    if not scannedUserResult.val():
        raise Exception
    scannedUser = scannedUserResult.val()

    scannerUserResult = FirebaseService.get([EVENT_ROOT, "users", scannerUserKey])
    if not scannerUserResult.val():
        raise Exception
    scannerUser = scannerUserResult.val()

    keyChoices = [scannedUserKey, scannerUserKey]
    winningKey = random.choice(keyChoices)

    if (winningKey == scannedUserKey):
        losingKey = scannerUserKey
        winner = scannedUser
        loser = scannerUser
    elif (winningKey == scannerUserKey):
        losingKey = scannedUserKey
        winner = scannerUser
        loser = scannedUser

    newWinnerScore = 2 + winner["score"]
    FirebaseService.set([EVENT_ROOT, "users", winningKey, "score"], newWinnerScore)
    
    newLoserScore = 1 + loser["score"]
    FirebaseService.set([EVENT_ROOT, "users", losingKey, "score"], newLoserScore)

    event = {"winner": winner["name"] + f' ({newWinnerScore} pts)', "loser": loser["name"] + f' ({newLoserScore} pts)', "winnerKey": winningKey, "loserKey": losingKey, "time": time}
    FirebaseService.push([EVENT_ROOT, "scoreboard"], event)
    return event

def getParticipantDataViaEmail(email):
    results = FirebaseService.query([EVENT_ROOT, "users"], "email", email)
    if not results:
        raise NoParticipantFound
    return results[0]

def getParticipantDataViaUserKey(userKey):
    result = FirebaseService.get([EVENT_ROOT, "users", userKey])
    return result.val()

def addParticipant(name, email, hashedPassword):
    emailHost = APIPropertiesManager.EMAIL_HOST
    emailPort = APIPropertiesManager.EMAIL_PORT
    emailSender = APIPropertiesManager.EMAIL_SENDER
    emailPassword = APIPropertiesManager.EMAIL_PASSWORD
    shutdownTime = getCurrentSeasonWindow()[1]
    webAppHost = APIPropertiesManager.WEBAPP_HOST
    try:
        getParticipantDataViaEmail(email)
        raise EmailInUse
    except NoParticipantFound:
        user = {"name": name, "email": email, "hashedPassword": hashedPassword, "score": 0}
        FirebaseService.push([EVENT_ROOT, "users"], user)

        userData = getParticipantDataViaEmail(email)
        userKey = userData[0]

        # create QR code to fight user
        qrCodeFightUrl = webAppHost + "/fight/?scannedUserKey="
        userQrCode = qrcode.make(qrCodeFightUrl + userKey)
        userQRCodeFileName = userKey + ".png"
        if not os.path.exists('QR Codes'):
            os.mkdir('QR Codes')
        userQRCodeFileLoc = "QR Codes/" + userQRCodeFileName
        userQrCode.save(userQRCodeFileLoc)

        # save QR code as base 64 to database
        with open(userQRCodeFileLoc, "rb") as f:
            encodedImage = base64.b64encode(f.read()).decode()
        FirebaseService.set([EVENT_ROOT, "users", userKey, "qrcode"], encodedImage)

        # get email properties
        emailReceivers = resolveRecipients([email])

        # create a themed welcome email (matches the season-start / results emails) with
        # the rules and the player's QR code embedded inline
        scoreboardUrl = webAppHost + "/scoreboard/"
        content = (
            f'<p style="margin:0 0 14px 0;">Hello {escapeHtml(name)},</p>'
            f'<p style="margin:0 0 18px 0;font-size:18px;color:#5f2f87;"><strong>Welcome to The Long Night!</strong></p>'
            f'<p style="margin:0 0 14px 0;">You have joined the hunt. Here is how it works:</p>'
            f'<div style="background-color:#000000;color:#ffff00;border:6px solid #c900cd;padding:12px 16px;margin:0 0 16px 0;">'
            f'<div style="font-weight:bold;margin-bottom:6px;">How to play</div>'
            f'<ol style="margin:0;padding-left:22px;">'
            f'<li>Scan another player\'s QR code to fight them -- each pair may fight only once.</li>'
            f'<li>The random winner of a fight gets 2 points; the loser gets 1.</li>'
            f'<li>Whoever has the most points when The Long Night ends ({shutdownTime}) wins.</li>'
            f'<li>You will be emailed a summary of everyone you faced when the season ends.</li>'
            f'</ol></div>'
            f'<p style="margin:0 0 16px 0;">Live scoreboard: {scoreboardUrl}</p>'
            f'<p style="margin:0 0 8px 0;font-weight:bold;">Your QR code</p>'
            f'<div style="text-align:center;margin:0 0 16px 0;">'
            f'<img src="cid:{userQRCodeFileName}" alt="Your personal QR code" width="220" '
            f'style="width:220px;max-width:70%;height:auto;background:#ffffff;border:6px solid #c900cd;padding:10px;"/>'
            f'</div>'
            f'<p style="margin:8px 0 0 0;">Good luck, and have fun!</p>'
        )
        body = styledEmail(content)
        
        msg = MIMEMultipart()
        msg['Subject'] = "Welcome to The Long Night!"
        msg['From'] = emailSender
        msg['To'] = ','.join(emailReceivers)

        msgText = MIMEText(body, 'html')
        msg.attach(msgText)

        with open(userQRCodeFileLoc, 'rb') as fp:
            emailImage = MIMEImage(fp.read())
        emailImage.add_header('Content-ID', '<{}>'.format(userQRCodeFileName))
        msg.attach(emailImage)

        # log into email host and send email
        server = smtplib.SMTP_SSL(emailHost, emailPort)
        server.login(emailSender, emailPassword)
        server.sendmail(emailSender, emailReceivers, msg.as_string())
        server.quit()

        return (userKey, encodedImage)

def updateParticipant(userKey, email, hashedPassword):
    FirebaseService.set([EVENT_ROOT, "users", userKey, "email"], email)
    FirebaseService.set([EVENT_ROOT, "users", userKey, "hashedPassword"], hashedPassword)    

def resolveRecipients(recipients):
    # QA safety net: when EMAIL_OVERRIDE_RECIPIENT is set, redirect ALL outgoing mail to
    # that single address so no real participants are emailed during testing. In normal
    # operation it's empty and the intended recipients are used unchanged.
    override = APIPropertiesManager.EMAIL_OVERRIDE_RECIPIENT
    if override:
        return [override]
    return list(recipients)

def styledEmail(contentHtml):
    # Inline-CSS, table-based HTML email themed to match the app (orange page,
    # purple header/footer, black cards with yellow text and magenta borders).
    # Mail clients strip <style>/external CSS, so every rule is inline here.
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#ffb94f" style="background-color:#ffb94f;margin:0;padding:24px 0;">'
        '<tr><td align="center">'
        '<table width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:600px;border-collapse:collapse;">'
        '<tr><td align="center" bgcolor="#5f2f87" style="background-color:#5f2f87;border:6px solid #c900cd;padding:22px 16px;">'
        '<div style="font-family:Georgia,serif;font-size:30px;font-weight:bold;color:#ffffff;letter-spacing:3px;">The Long Night</div>'
        '<div style="font-family:Georgia,serif;font-size:13px;color:#ffb94f;letter-spacing:3px;padding-top:4px;">A StormerG Halloween Game</div>'
        '</td></tr>'
        '<tr><td bgcolor="#ffffff" style="background-color:#ffffff;border-left:6px solid #c900cd;border-right:6px solid #c900cd;padding:24px 20px;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:1.5;color:#000000;">'
        + contentHtml +
        '</td></tr>'
        '<tr><td align="center" bgcolor="#5f2f87" style="background-color:#5f2f87;border:6px solid #c900cd;padding:14px;font-family:Georgia,serif;font-size:18px;letter-spacing:2px;color:#ffffff;">Happy Halloween</td></tr>'
        '</table>'
        '</td></tr></table>'
    )

def emailResults():
    emailHost = APIPropertiesManager.EMAIL_HOST
    emailPort = APIPropertiesManager.EMAIL_PORT
    emailSender = APIPropertiesManager.EMAIL_SENDER
    emailPassword = APIPropertiesManager.EMAIL_PASSWORD
    scoreboard = getScoreboard()
    topScore = getTopScore()

    result = FirebaseService.get([EVENT_ROOT, "users"])
    if result.val() != None:
        users = result.val()
    else:
        raise Exception

    emailDictionary = dict()
    winningEmails = []
    winningNames = ""
    for userKey, userValue in users.items():
        email = userValue["email"]
        name = userValue["name"]
        score = userValue["score"]

        if score == topScore:
            winningEmails.append(email)
            winningNames += f'<li>{escapeHtml(name)}</li>'

        # create empty buckets for users' interactions
        emailDictionary[userKey] = {"email": email, "name": name, "score": score, "interactions": ""}

    # fill buckets up with users' interactions they've had
    for event in scoreboard:
        winnerKey = event["winnerKey"]
        loserKey = event["loserKey"]
        time = event["time"]
        emailDictionary[winnerKey]["interactions"] += (f'<li>You defeated {escapeHtml(emailDictionary[loserKey]["name"])}. {escapeHtml(time)}</li>')
        emailDictionary[loserKey]["interactions"] += (f'<li>You lost to {escapeHtml(emailDictionary[winnerKey]["name"])}. {escapeHtml(time)}</li>')
    
    # get email properties
    server = smtplib.SMTP_SSL(emailHost, emailPort)
    server.login(emailSender, emailPassword)

    # send out unique emails to all users
    for emailValue in emailDictionary.values():
        emailReceivers = resolveRecipients([emailValue["email"]])

        # Winner and loser emails share one template so they stay consistent --
        # only the outcome line differs.
        if emailValue["email"] in winningEmails:
            outcome = f'Congratulations! You finished with the top score of {topScore} points!'
        else:
            outcome = f'You did not have the top score of {topScore} points this time.'
        content = (
            f'<p style="margin:0 0 14px 0;">Hello {escapeHtml(emailValue["name"])},</p>'
            f'<p style="margin:0 0 18px 0;font-size:18px;color:#5f2f87;"><strong>You have survived The Long Night!</strong> {outcome}</p>'
            f'<div style="background-color:#000000;color:#ffff00;border:6px solid #c900cd;padding:12px 16px;margin:0 0 16px 0;">'
            f'<div style="font-weight:bold;margin-bottom:6px;">Winners with top score</div>'
            f'<ol style="margin:0;padding-left:22px;">{winningNames}</ol></div>'
            f'<div style="background-color:#000000;color:#ffff00;border:6px solid #c900cd;padding:12px 16px;margin:0 0 16px 0;">'
            f'<div style="font-weight:bold;margin-bottom:6px;">Your interactions</div>'
            f'<ol style="margin:0;padding-left:22px;">{emailValue["interactions"]}</ol></div>'
            f'<p style="margin:8px 0 0 0;">Thanks for playing The Long Night! It returns next '
            f'October -- watch for an email when the new season begins.</p>'
        )
        body = styledEmail(content)

        msg = MIMEText(body, 'html')
        msg['Subject'] = "Your watch has ended."
        msg['From'] = emailSender
        msg['To'] = ','.join(emailReceivers)

        # log into email host and send email
        server.sendmail(emailSender, emailReceivers, msg.as_string())
    
    server.quit()