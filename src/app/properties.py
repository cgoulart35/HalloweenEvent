#region IMPORTS
import os
import logging

from src.common.exceptions import PropertyNotSpecified
#endregion

class WebAppPropertiesManager:
    logger = logging.getLogger()

    # API PROPERTIES
    VERSION = None
    TZ = None
    LOG_LEVEL = None
    WEBAPP_PORT = None
    SCHEDULED_SHUTDOWN_TIME = None
    SECRET_KEY = None

    # COMMUNICATION PROPERTIES
    API_HOST = None
    
    # CREDENTIAL PROPERTIES
    FIREBASE_CONFIG_JSON = None

    def startPropertyManager():
        # initialize properties
        WebAppPropertiesManager.VERSION =                  WebAppPropertiesManager.getEnvProperty("VERSION")                        # required
        WebAppPropertiesManager.TZ =                       WebAppPropertiesManager.getEnvProperty("TZ", "America/New_York")         # not required, usable when not given
        WebAppPropertiesManager.LOG_LEVEL =                WebAppPropertiesManager.getEnvProperty("LOG_LEVEL", "INFO")              # not required, usable when not given
        WebAppPropertiesManager.WEBAPP_PORT =              WebAppPropertiesManager.getEnvProperty("WEBAPP_PORT", "5002")            # not required, usable when not given
        WebAppPropertiesManager.SCHEDULED_SHUTDOWN_TIME =  WebAppPropertiesManager.getEnvProperty("SCHEDULED_SHUTDOWN_TIME")        # required
        WebAppPropertiesManager.SECRET_KEY =               WebAppPropertiesManager.getEnvProperty("SECRET_KEY", "super secret key") # not required, usable when not given

        WebAppPropertiesManager.API_HOST =                 WebAppPropertiesManager.getEnvProperty("API_HOST")                       # required

        WebAppPropertiesManager.FIREBASE_CONFIG_JSON =     WebAppPropertiesManager.getEnvProperty("FIREBASE_CONFIG_JSON")           # required

    def getEnvProperty(property, default = None):
        value = os.getenv(property)
        if value:
            return WebAppPropertiesManager.determineValue(property, value)
        elif default != None:
            return default
        else:
            WebAppPropertiesManager.logger.error('Required WebApp property not specified: ' + property)
            raise PropertyNotSpecified
        
    def determineValue(property, value):
        INT_PROPERTIES = [
            "WEBAPP_PORT"
        ]
        if property in INT_PROPERTIES:
            return int(value)
        elif property == "LOG_LEVEL":
            return WebAppPropertiesManager.getLogLevel(value)
        else:
            return value                
        
    def setProperty(property, value):
        ### IMMUTABLE PROPERTIES ###

        # if property == "VERSION":
        #     WebAppPropertiesManager.VERSION = value
        # elif property == "TZ":
        #     WebAppPropertiesManager.TZ = value
        # elif property == "WEBAPP_PORT":
        #     WebAppPropertiesManager.WEBAPP_PORT = value
        # elif property == "SECRET_KEY":
        #     WebAppPropertiesManager.SECRET_KEY = value
        # elif property == "FIREBASE_CONFIG_JSON":
        #     WebAppPropertiesManager.FIREBASE_CONFIG_JSON = value

        ### MUTABLE PROPERTIES ###

        if property == "LOG_LEVEL":
            WebAppPropertiesManager.LOG_LEVEL = value
            WebAppPropertiesManager.logger.setLevel(WebAppPropertiesManager.getLogLevel(WebAppPropertiesManager.LOG_LEVEL))
        elif property == "SCHEDULED_SHUTDOWN_TIME":
            WebAppPropertiesManager.SCHEDULED_SHUTDOWN_TIME = value
        elif property == "WEBAPP_HOST":
            WebAppPropertiesManager.WEBAPP_HOST = value
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