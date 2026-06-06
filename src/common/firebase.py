#region IMPORTS
import json
import firebase_admin
from firebase_admin import credentials, db
#endregion

class _Result:
    # thin adapter so existing call sites can keep using .val() (as Pyrebase did)
    def __init__(self, value):
        self._value = value

    def val(self):
        return self._value

class FirebaseService:
    app = None

    def startFirebaseScheduler(configJson):
        # initialize firebase-admin with the service account + database URL from config
        config = json.loads(configJson)
        if not firebase_admin._apps:
            cred = credentials.Certificate(config["serviceAccount"])
            FirebaseService.app = firebase_admin.initialize_app(cred, {
                "databaseURL": config["databaseURL"]
            })

    def reference(children):
        return db.reference("/" + "/".join(children))

    def get(children):
        return _Result(FirebaseService.reference(children).get())

    def remove(children):
        FirebaseService.reference(children).delete()

    def set(children, object):
        FirebaseService.reference(children).set(object)

    def push(children, object):
        FirebaseService.reference(children).push(object)

    def update(children, object):
        FirebaseService.reference(children).update(object)

    def query(children, orderByChild, equalTo):
        # returns a list of (key, value) tuples matching the equality filter
        result = FirebaseService.reference(children).order_by_child(orderByChild).equal_to(equalTo).get()
        if not result:
            return []
        return list(result.items())
