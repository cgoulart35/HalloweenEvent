#region IMPORTS
import json
import pyrebase
#endregion

class FirebaseService:
    db = None
    auth = None

    def startFirebaseScheduler(configJson):
        # initialize firebase and database
        firebaseConfigJsonObj = json.loads(configJson)
        firebase = pyrebase.initialize_app(firebaseConfigJsonObj)
        FirebaseService.db = firebase.database()
        FirebaseService.auth = firebase.auth()

    def authenticate(username, password):
        try:
            FirebaseService.auth.sign_in_with_email_and_password(username, password)
            return True
        except:
            return False

    def getDbObj(children):
        dbObj = FirebaseService.loopChildren(children)
        return dbObj

    def get(children):
        dbObj = FirebaseService.loopChildren(children)
        return dbObj.get()

    def remove(children):
        dbObj = FirebaseService.loopChildren(children)
        dbObj.remove()

    def set(children, object):
        dbObj = FirebaseService.loopChildren(children)
        dbObj.set(object)

    def push(children, object):
        dbObj = FirebaseService.loopChildren(children)
        dbObj.push(object)

    def update(children, object):
        dbObj = FirebaseService.loopChildren(children)
        dbObj.update(object)
    
    def loopChildren(children):
        dbObj = FirebaseService.db
        for child in children:
            dbObj = dbObj.child(child)
        return dbObj
