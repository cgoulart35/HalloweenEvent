#region IMPORTS
import qrcode
import random
import smtplib
import os
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

from src.api.properties import APIPropertiesManager
from src.common.firebase import FirebaseService
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
    scoreboard = getScoreboard()
    if scoreboard != []:    
        for event in scoreboard:
            if (event["winnerKey"] == scannedUserKey and event["loserKey"] == scannerUserKey) or event["winnerKey"] == scannerUserKey and event["loserKey"] == scannedUserKey:
                return False

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

def getParticipantKey(email):
    result = FirebaseService.getDbObj(["halloween-event", "users"]).order_by_child("email").equal_to(email).get()
    if not result.val():
        raise Exception
    return result.pyres[0].item[0]

def addParticipant(name, email):
    emailHost = APIPropertiesManager.EMAIL_HOST
    emailPort = APIPropertiesManager.EMAIL_PORT
    emailSender = APIPropertiesManager.EMAIL_SENDER
    emailPassword = APIPropertiesManager.EMAIL_PASSWORD
    shutdownTime = APIPropertiesManager.SCHEDULED_SHUTDOWN_TIME
    webAppHost = APIPropertiesManager.WEBAPP_HOST
    try:
        getParticipantKey(email)
    except:
        user = {"name": name, "email": email, "score": 0}
        FirebaseService.push(["halloween-event", "users"], user)

        userKey = getParticipantKey(email)

        # create QR code to fight user
        
        qrCodeFightUrl = webAppHost + "/halloween/fight/?scannedUserKey="
        userQrCode = qrcode.make(qrCodeFightUrl + userKey)
        userQRCodeFileName = userKey + ".png"
        if not os.path.exists('QR Codes'):
            os.mkdir('QR Codes')
        userQRCodeFileLoc = "QR Codes/" + userQRCodeFileName
        userQrCode.save(userQRCodeFileLoc)

        # get email properties
        emailReceivers = [email]

        # create an email with instructions and user's QR code
        scoreboardUrl = webAppHost + "/halloween/scoreboard/"
        rules = f'<ol><li>A QR code has been created for you.</li><li>Scan as many other players\' QR codes as you can to fight them once.</li><li>The random winner of a fight will get 2 points and the loser will get 1 point.</li><li>The player with the most points at the end of the night by {shutdownTime} wins.</li><li>You will be sent a summary at the end of the night of who you interacted with!</li><li>Have fun!</li></ol>'
        body = f'<br>Hello {name},<br><br>Welcome to The Long Night!<br><br>Rules:<br>{rules}<br>Live Scoreboard: (log in through email only - don\'t share it!) {scoreboardUrl}<br><br>Your QR Code:<br>'
        
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

        return userKey

    raise Exception

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

        # create an email with users' score, interactions, and win status (if had top score)
        if emailValue["email"] not in winningEmails:
            body = f'<br>Hello {emailValue["name"]},<br><br>You have survived The Long Night! However, you did not have the top score of {topScore} points.<br><br>Winners with top score:<ol>{winningNames}</ol><br>Your interactions:<br><ol>{emailValue["interactions"]}</ol><br>Thanks for playing The Long Night!'
        else:
            body = f'<br>Hello {emailValue["name"]},<br><br>Congratulations! You had the top score of {topScore} points!<br><br>Winners with top score:<ol>{winningNames}</ol><br>Your interactions:<br><ol>{emailValue["interactions"]}</ol><br>Thanks for playing The Long Night!'

        msg = MIMEText('<b>%s</b>' % (body), 'html')
        msg['Subject'] = "Your watch has ended."
        msg['From'] = emailSender
        msg['To'] = ','.join(emailReceivers)

        # log into email host and send email
        server.sendmail(emailSender, emailReceivers, msg.as_string())
    
    server.quit()