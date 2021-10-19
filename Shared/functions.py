import configparser
import json
import pyrebase
from flask import send_from_directory

def favicon(parentDir):
    return send_from_directory(parentDir + '/Shared', 'favicon.ico')

def buildSharedConfig(parentDir):
    sharedConfig = configparser.ConfigParser()
    sharedConfig.read(parentDir + '/Shared/shared.ini')
    return sharedConfig

def buildFirebase(firebaseConfigJson):
    firebaseConfig = json.loads(firebaseConfigJson)
    return pyrebase.initialize_app(firebaseConfig)