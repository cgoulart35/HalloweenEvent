#region IMPORTS
import os
import logging
import secrets

from src.common.exceptions import PropertyNotSpecified
#endregion

class WebAppPropertiesManager:
    logger = logging.getLogger()

    # API PROPERTIES
    VERSION = None
    TZ = None
    LOG_LEVEL = None
    WEBAPP_PORT = None
    SECRET_KEY = None

    # COMMUNICATION PROPERTIES
    API_HOST = None
    API_KEY = None

    # CREDENTIAL PROPERTIES
    FIREBASE_CONFIG_JSON = None

    # CAPTCHA PROPERTIES
    TURNSTILE_SITE_KEY = None
    TURNSTILE_SECRET_KEY = None

    def startPropertyManager():
        # initialize properties
        WebAppPropertiesManager.VERSION =                  WebAppPropertiesManager.getEnvProperty("VERSION")                        # required
        WebAppPropertiesManager.TZ =                       WebAppPropertiesManager.getEnvProperty("TZ", "America/New_York")         # not required, usable when not given
        WebAppPropertiesManager.LOG_LEVEL =                WebAppPropertiesManager.getEnvProperty("LOG_LEVEL", "INFO")              # not required, usable when not given
        WebAppPropertiesManager.WEBAPP_PORT =              WebAppPropertiesManager.getEnvProperty("WEBAPP_PORT", "5002")            # not required, usable when not given
        secretKey = os.getenv("SECRET_KEY", "")
        if not secretKey:
            secretKey = secrets.token_hex(32)
            WebAppPropertiesManager.logger.warning("SECRET_KEY not set; using a random per-boot key. Set SECRET_KEY in app.env for stable sessions.")
        WebAppPropertiesManager.SECRET_KEY = secretKey

        WebAppPropertiesManager.API_HOST =                 WebAppPropertiesManager.getEnvProperty("API_HOST")                       # required
        WebAppPropertiesManager.API_KEY =                  WebAppPropertiesManager.getEnvProperty("API_KEY")                        # required

        WebAppPropertiesManager.FIREBASE_CONFIG_JSON =     WebAppPropertiesManager.getEnvProperty("FIREBASE_CONFIG_JSON")           # required

        WebAppPropertiesManager.TURNSTILE_SITE_KEY =       WebAppPropertiesManager.getEnvProperty("TURNSTILE_SITE_KEY", "")         # optional; empty = CAPTCHA disabled
        WebAppPropertiesManager.TURNSTILE_SECRET_KEY =     WebAppPropertiesManager.getEnvProperty("TURNSTILE_SECRET_KEY", "")       # optional; empty = CAPTCHA disabled

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
        elif property == "API_HOST":
            WebAppPropertiesManager.API_HOST = value
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