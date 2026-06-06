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
from src.common.exceptions import NoParticipantFound, EmailInUse, NotAllowedToFightSelf, NotAllowedToFightAgain
#endregion

def getScoreboard():
    result = FirebaseService.get(["halloween-event", "scoreboard"])
    if result.val() != None:
        scoreboard = result.val()
        if isinstance(scoreboard, dict):
            return sorted(scoreboard.values(), key=lambda event: datetime.strptime(event["time"], "%m/%d/%y %I:%M:%S %p"), reverse=True)
        else:
            return sorted(scoreboard, key=lambda event: datetime.strptime(event["time"], "%m/%d/%y %I:%M:%S %p"), reverse=True)
    else:
        return []

def getTopScore():
    result = FirebaseService.get(["halloween-event", "users"])
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

    scannedUserResult = FirebaseService.get(["halloween-event", "users", scannedUserKey])
    if not scannedUserResult.val():
        raise Exception
    scannedUser = scannedUserResult.val()

    scannerUserResult = FirebaseService.get(["halloween-event", "users", scannerUserKey])
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
    FirebaseService.set(["halloween-event", "users", winningKey, "score"], newWinnerScore)
    
    newLoserScore = 1 + loser["score"]
    FirebaseService.set(["halloween-event", "users", losingKey, "score"], newLoserScore)

    event = {"winner": winner["name"] + f' ({newWinnerScore} pts)', "loser": loser["name"] + f' ({newLoserScore} pts)', "winnerKey": winningKey, "loserKey": losingKey, "time": time}
    FirebaseService.push(["halloween-event", "scoreboard"], event)
    return event

def getParticipantDataViaEmail(email):
    results = FirebaseService.query(["halloween-event", "users"], "email", email)
    if not results:
        raise NoParticipantFound
    return results[0]

def getParticipantDataViaUserKey(userKey):
    result = FirebaseService.get(["halloween-event", "users", userKey])
    return result.val()

def addParticipant(name, email, hashedPassword):
    emailHost = APIPropertiesManager.EMAIL_HOST
    emailPort = APIPropertiesManager.EMAIL_PORT
    emailSender = APIPropertiesManager.EMAIL_SENDER
    emailPassword = APIPropertiesManager.EMAIL_PASSWORD
    shutdownTime = APIPropertiesManager.SCHEDULED_SHUTDOWN_TIME
    webAppHost = APIPropertiesManager.WEBAPP_HOST
    try:
        getParticipantDataViaEmail(email)
        raise EmailInUse
    except NoParticipantFound:
        user = {"name": name, "email": email, "hashedPassword": hashedPassword, "score": 0}
        FirebaseService.push(["halloween-event", "users"], user)

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
        FirebaseService.set(["halloween-event", "users", userKey, "qrcode"], encodedImage)

        # get email properties
        emailReceivers = [email]

        # create an email with instructions and user's QR code
        scoreboardUrl = webAppHost + "/scoreboard/"
        rules = f'<ol><li>A QR code has been created for you.</li><li>Scan as many other players\' QR codes to fight them once.</li><li>The random winner of a fight will get 2 points and the loser will get 1 point.</li><li>The player with the most points at the end of The Long Night by {shutdownTime} wins.</li><li>You will be sent a summary at the end of The Long Night of who you interacted with!</li><li>Have fun!</li></ol>'
        body = f'<br>Hello {name},<br><br>Welcome to The Long Night!<br><br>Rules:<br>{rules}<br>Live Scoreboard: {scoreboardUrl}<br><br>Your QR Code:<br>'
        
        msg = MIMEMultipart()
        msg['Subject'] = "Welcome to The Long Night!"
        msg['From'] = emailSender
        msg['To'] = ','.join(emailReceivers)

        msgText = MIMEText('<b>%s</b><br><img src="cid:%s"/><br>' % (body, userQRCodeFileName), 'html')
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
    FirebaseService.set(["halloween-event", "users", userKey, "email"], email)
    FirebaseService.set(["halloween-event", "users", userKey, "hashedPassword"], hashedPassword)    

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

    result = FirebaseService.get(["halloween-event", "users"])
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
            winningNames += f'<li>{name}</li>'

        # create empty buckets for users' interactions
        emailDictionary[userKey] = {"email": email, "name": name, "score": score, "interactions": ""}

    # fill buckets up with users' interactions they've had
    for event in scoreboard:
        winnerKey = event["winnerKey"]
        loserKey = event["loserKey"]
        time = event["time"]
        emailDictionary[winnerKey]["interactions"] += (f'<li>You defeated {emailDictionary[loserKey]["name"]}. {time}</li>')
        emailDictionary[loserKey]["interactions"] += (f'<li>You lost to {emailDictionary[winnerKey]["name"]}. {time}</li>')
    
    # get email properties
    server = smtplib.SMTP_SSL(emailHost, emailPort)
    server.login(emailSender, emailPassword)

    # send out unique emails to all users
    for emailValue in emailDictionary.values():
        emailReceivers = [emailValue["email"]]

        # Winner and loser emails share one template so they stay consistent --
        # only the outcome line differs.
        if emailValue["email"] in winningEmails:
            outcome = f'Congratulations! You finished with the top score of {topScore} points!'
        else:
            outcome = f'You did not have the top score of {topScore} points this time.'
        content = (
            f'<p style="margin:0 0 14px 0;">Hello {emailValue["name"]},</p>'
            f'<p style="margin:0 0 18px 0;font-size:18px;color:#5f2f87;"><strong>You have survived The Long Night!</strong> {outcome}</p>'
            f'<div style="background-color:#000000;color:#ffff00;border:6px solid #c900cd;padding:12px 16px;margin:0 0 16px 0;">'
            f'<div style="font-weight:bold;margin-bottom:6px;">Winners with top score</div>'
            f'<ol style="margin:0;padding-left:22px;">{winningNames}</ol></div>'
            f'<div style="background-color:#000000;color:#ffff00;border:6px solid #c900cd;padding:12px 16px;margin:0 0 16px 0;">'
            f'<div style="font-weight:bold;margin-bottom:6px;">Your interactions</div>'
            f'<ol style="margin:0;padding-left:22px;">{emailValue["interactions"]}</ol></div>'
            f'<p style="margin:8px 0 0 0;">Thanks for playing The Long Night!</p>'
        )
        body = styledEmail(content)

        msg = MIMEText(body, 'html')
        msg['Subject'] = "Your watch has ended."
        msg['From'] = emailSender
        msg['To'] = ','.join(emailReceivers)

        # log into email host and send email
        server.sendmail(emailSender, emailReceivers, msg.as_string())
    
    server.quit()