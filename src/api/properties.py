#region IMPORTS
import os
import logging

from src.common.exceptions import PropertyNotSpecified
#endregion

class APIPropertiesManager:
    logger = logging.getLogger()

    # API PROPERTIES
    VERSION = None
    TZ = None
    LOG_LEVEL = None
    API_PORT = None
    SCHEDULED_SHUTDOWN_TIME = None

    # COMMUNICATION PROPERTIES
    WEBAPP_HOST = None
    
    # CREDENTIAL PROPERTIES
    FIREBASE_CONFIG_JSON = None
    
    # EMAIL PROPERTIES
    EMAIL_HOST = None
    EMAIL_PORT = None
    EMAIL_SENDER = None
    EMAIL_PASSWORD = None

    def startPropertyManager():
        # initialize properties
        APIPropertiesManager.VERSION =                  APIPropertiesManager.getEnvProperty("VERSION")                 # required
        APIPropertiesManager.TZ =                       APIPropertiesManager.getEnvProperty("TZ", "America/New_York")  # not required, usable when not given
        APIPropertiesManager.LOG_LEVEL =                APIPropertiesManager.getEnvProperty("LOG_LEVEL", "INFO")       # not required, usable when not given
        APIPropertiesManager.API_PORT =                 APIPropertiesManager.getEnvProperty("API_PORT", "5001")        # not required, usable when not given
        APIPropertiesManager.SCHEDULED_SHUTDOWN_TIME =  APIPropertiesManager.getEnvProperty("SCHEDULED_SHUTDOWN_TIME") # required

        APIPropertiesManager.WEBAPP_HOST =              APIPropertiesManager.getEnvProperty("WEBAPP_HOST")             # required

        APIPropertiesManager.FIREBASE_CONFIG_JSON =     APIPropertiesManager.getEnvProperty("FIREBASE_CONFIG_JSON")    # required

        APIPropertiesManager.EMAIL_HOST =               APIPropertiesManager.getEnvProperty("EMAIL_HOST")              # required
        APIPropertiesManager.EMAIL_PORT =               APIPropertiesManager.getEnvProperty("EMAIL_PORT")              # required
        APIPropertiesManager.EMAIL_SENDER =             APIPropertiesManager.getEnvProperty("EMAIL_SENDER")            # required
        APIPropertiesManager.EMAIL_PASSWORD =           APIPropertiesManager.getEnvProperty("EMAIL_PASSWORD")          # required

    def getEnvProperty(property, default = None):
        value = os.getenv(property)
        if value:
            return APIPropertiesManager.determineValue(property, value)
        elif default != None:
            return default
        else:
            APIPropertiesManager.logger.error('Required API property not specified: ' + property)
            raise PropertyNotSpecified
        
    def determineValue(property, value):
        INT_PROPERTIES = [
            "API_PORT"
        ]
        if property in INT_PROPERTIES:
            return int(value)
        elif property == "LOG_LEVEL":
            return APIPropertiesManager.getLogLevel(value)
        else:
            return value                
        
    def setProperty(property, value):
        ### IMMUTABLE PROPERTIES ###

        # if property == "VERSION":
        #     APIPropertiesManager.VERSION = value
        # elif property == "TZ":
        #     APIPropertiesManager.TZ = value
        # elif property == "API_PORT":
        #     APIPropertiesManager.API_PORT = value
        # elif property == "FIREBASE_CONFIG_JSON":
        #     APIPropertiesManager.FIREBASE_CONFIG_JSON = value

        ### MUTABLE PROPERTIES ###

        if property == "LOG_LEVEL":
            APIPropertiesManager.LOG_LEVEL = value
            APIPropertiesManager.logger.setLevel(APIPropertiesManager.getLogLevel(APIPropertiesManager.LOG_LEVEL))
        elif property == "SCHEDULED_SHUTDOWN_TIME":
            APIPropertiesManager.SCHEDULED_SHUTDOWN_TIME = value
        elif property == "WEBAPP_HOST":
            APIPropertiesManager.WEBAPP_HOST = value
        elif property == "EMAIL_HOST":
            APIPropertiesManager.EMAIL_HOST = value
        elif property == "EMAIL_PORT":
            APIPropertiesManager.EMAIL_PORT = value
        elif property == "EMAIL_SENDER":
            APIPropertiesManager.EMAIL_SENDER = value
        elif property == "EMAIL_PASSWORD":
            APIPropertiesManager.EMAIL_PASSWORD = value
        else:
            return False
        return True
    
    def getLogLevel(level):
        if level == "CRITICAL":
            return logging.CRITICAL
        elif level == "FATAL":
            return logging.FATAL
        elif level == "ERROR":
            return logging.ERROR
        elif level == "WARNING":
            return logging.WARNING
        elif level == "WARN":
            return logging.WARN
        elif level == "INFO":
            return logging.INFO
        elif level == "DEBUG":
            return logging.DEBUG
        else:
            return logging.NOTSET