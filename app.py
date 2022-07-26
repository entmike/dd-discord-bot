from io import BytesIO, StringIO
from operator import truediv
from turtle import color
from pydotted import pydot
import requests
import jsbeautifier
import os, sys
from webbrowser import get
from flask import Flask, flash, request, redirect, url_for, jsonify, send_file
from flask_cors import CORS, cross_origin
from dotenv import load_dotenv
from yaml import dump, full_load
from werkzeug.utils import secure_filename
import hashlib
from datetime import datetime, timedelta
from bson import Binary, Code
from bson.json_util import dumps
import uuid
import json
from loguru import logger
from PIL import Image
import boto3
import botocore.exceptions
from six.moves.urllib.request import urlopen
from functools import wraps
from jose import jwt
from flask import _request_ctx_stack
from colorthief import ColorThief

# from .auth import current_user

AUTH0_DOMAIN = "dev-yqzsn326.auth0.com"
API_AUDIENCE = "https://api.feverdreams.app/"
ALGORITHMS = ["RS256"]

# https://iq-inc.com/wp-content/uploads/2021/02/AndyRelativeImports-300x294.jpg
sys.path.append(".")
from db import get_database

load_dotenv()

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "log", "lz4"}
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_STALL_TIMEOUT = 180
BOT_SALT = os.getenv("BOT_SALT")
BOT_USE_S3 = os.getenv("BOT_USE_S3")
BOT_S3_BUCKET = os.getenv("BOT_S3_BUCKET")
BOT_S3_WEB = os.getenv("BOT_S3_WEB")
BOT_AWS_SERVER_PUBLIC_KEY = os.getenv("BOT_AWS_SERVER_PUBLIC_KEY")
BOT_AWS_SERVER_SECRET_KEY = os.getenv("BOT_AWS_SERVER_SECRET_KEY")
BOT_WEBSITE = os.getenv("BOT_WEBSITE")
MAX_DREAM_OCCURENCE = os.getenv("MAX_DREAM_OCCURENCE")
ALGOLIA_APP_ID = os.getenv("ALGOLIA_APP_ID")
ALGOLIA_API_KEY = os.getenv("ALGOLIA_API_KEY")
ALGOLIA_INDEX_NAME = os.getenv("ALGOLIA_INDEX_NAME")


if BOT_USE_S3:
    session = boto3.Session(aws_access_key_id=BOT_AWS_SERVER_PUBLIC_KEY, aws_secret_access_key=BOT_AWS_SERVER_SECRET_KEY)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
CORS(app)

# Format error response and append status code
def get_token_auth_header():
    """Obtains the Access Token from the Authorization Header"""
    auth = request.headers.get("Authorization", None)
    if not auth:
        raise AuthError({"code": "authorization_header_missing", "description": "Authorization header is expected"}, 401)

    parts = auth.split()

    if parts[0].lower() != "bearer":
        raise AuthError({"code": "invalid_header", "description": "Authorization header must start with" " Bearer"}, 401)
    elif len(parts) == 1:
        raise AuthError({"code": "invalid_header", "description": "Token not found"}, 401)
    elif len(parts) > 2:
        raise AuthError({"code": "invalid_header", "description": "Authorization header must be" " Bearer token"}, 401)

    token = parts[1]
    # logger.info(token)
    return token


def requires_auth(f):
    """Determines if the Access Token is valid"""

    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_auth_header()
        jsonurl = urlopen("https://" + AUTH0_DOMAIN + "/.well-known/jwks.json")
        jwks = json.loads(jsonurl.read())
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        # logger.info(unverified_header)
        for key in jwks["keys"]:
            # logger.info(key)
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {"kty": key["kty"], "kid": key["kid"], "use": key["use"], "n": key["n"], "e": key["e"]}
        if rsa_key:
            try:
                payload = jwt.decode(token, rsa_key, algorithms=ALGORITHMS, audience=API_AUDIENCE, issuer="https://" + AUTH0_DOMAIN + "/")
            except jwt.ExpiredSignatureError:
                raise AuthError({"code": "token_expired", "description": "token is expired"}, 401)
            except jwt.JWTClaimsError:
                raise AuthError({"code": "invalid_claims", "description": "incorrect claims, please check the audience and issuer"}, 401)
            except Exception:
                raise AuthError({"code": "invalid_header", "description": "Unable to parse authentication token."}, 401)

            _request_ctx_stack.top.current_user = payload
            return f(*args, **kwargs)
        raise AuthError({"code": "invalid_header", "description": "Unable to find appropriate key"}, 401)

    return decorated


def upload_file_s3(file_name, bucket, object_name=None, extra_args=None):
    """Upload a file to an S3 bucket

    :param file_name: File to upload
    :param bucket: Bucket to upload to
    :param object_name: S3 object name. If not specified then file_name is used
    :return: True if file was uploaded, else False
    """

    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = os.path.basename(file_name)

    # Upload the file
    s3_client = boto3.client("s3")

    # s3_client = session.resource('s3')
    try:
        response = s3_client.upload_file(file_name, bucket, object_name, extra_args)
    except Exception as e:
        logger.error(e)
        return False
    return True


# Error handler
class AuthError(Exception):
    def __init__(self, error, status_code):
        self.error = error
        self.status_code = status_code


@app.errorhandler(AuthError)
def handle_auth_error(ex):
    response = jsonify(ex.error)
    response.status_code = ex.status_code
    return response


@app.route("/register/<agent_id>")
def register(agent_id):
    status = ""
    with get_database() as client:
        agentCollection = client.database.get_collection("agents")
        if agentCollection.count_documents({"agent_id": agent_id}) == 0:
            found = False
        else:
            found = True

        if not found:
            token = hashlib.sha256(f"{agent_id}{BOT_SALT}".encode("utf-8")).hexdigest()
            agentCollection.insert_one({"agent_id": agent_id, "last_seen": datetime.now()})
            status = f"✅ Registered!  Your API token is '{token}'.  Save this, you won't see it again."
            log(f"A new agent has joined! 😍 Thank you, {agent_id}!", title="🆕 New Agent")
            success = True
        else:
            status = f"😓 Sorry, someone already registered an agent by that name.  Try another one!"
            success = False
    return jsonify({"message": status, "success": success})


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def log(message, title="Message"):
    with get_database() as client:
        logTable = client.database.get_collection("logs")
        logTable.insert_one({"timestamp": str(datetime.now()), "message": message, "title": title, "ack": False, "uuid": str(uuid.uuid4())})


def event(event):
    return
    with get_database() as client:
        eventTable = client.database.get_collection("events")
        eventTable.insert_one({"timestamp": str(datetime.now()), "ack": False, "uuid": str(uuid.uuid4()), "event": event})
    logger.info(f"Event logged: {event}")


@app.route("/pin", methods=["POST","DELETE"])
@requires_auth
def pin():
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    uuid = request.json.get("uuid")
    if request.method == "DELETE":
        client.database.get_collection("pins").delete_one({"user_id": discord_id, "uuid" : uuid})
        return dumps({"message": "Unpinned"})

    if request.method == "POST":
        with get_database() as client:
            client.database.get_collection("pins").update_one({"user_id": discord_id}, {
                "$set": {
                    "pinned_on": datetime.now(),
                    "uuid": uuid
                }
            }, upsert=True)
        
        return dumps({"message": "Pinned"})

@app.route("/following", methods=["GET"])
@requires_auth
def following():
    current_user = _request_ctx_stack.top.current_user
    discord_id = current_user["sub"].split("|")[2]
    logger.info(f"Request for following list by {discord_id}...")
    with get_database() as client:
        following = client.database.vw_users.aggregate([
            { "$match" : { "user_id_str" : str(discord_id) } },
            { "$lookup": {
                "as": "following",
                "from" : "follows",
                "let" : { "userId" : "$user_id" },
                "pipeline": [
                    { "$match": { "$expr": { "$eq": [ "$user_id", "$$userId" ] } } },
                    { "$lookup" : {
                    "as" : "details",
                    "from" : "users",
                    "let" : {"followId" : "$follow_id"
                },
                    "pipeline" : [   
                        { "$match": {   
                        "$expr": {
                            "$eq": [ "$user_id", "$$followId" ]
                        } 
                        } },
                    ]
                    }},
                    {
                    "$unwind": "$details"
                    }
                ]
            }}
        ])
        following = list(following)
        return dumps(following)

@app.route("/following/feed", methods=["GET"])
@requires_auth
def following_feed():
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    logger.info(f"Request for following feed by {discord_id}...")
    with get_database() as client:
        following = client.database.get_collection("follows").aggregate([
            {
                '$match': {
                    'user_id': discord_id
                }
            }, {
                '$lookup': {
                    'from': 'completed_clean', 
                    'localField': 'author_id', 
                    'foreignField': 'follow_id', 
                    'as': 'jobs'
                }
            }, {
                '$unwind': '$jobs'
            }, {
                '$project': {
                    'follow_id': 1, 
                    'uuid': "$jobs.uuid",
                    'thumbnails': "$jobs.thumbnails",
                    'text_prompt' : "$jobs.text_prompt"
                    # 'jobs': {
                    #     'uuid': 1, 
                    #     'text_prompt': 1,
                    #     'thumbnails' : 1
                    # }
                }
            },{
                '$limit': 100
            }
        ])
        following = list(following)
        return dumps(following)

@app.route("/follow/<follow_id>", methods=["GET","POST","DELETE"])
@requires_auth
def follow(follow_id):
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])

    if request.method == "DELETE":
        with get_database() as client:
            client.database.get_collection("follows").delete_one({"user_id": discord_id, "follow_id" : int(follow_id)})
        
        return dumps({
            "message": "Unfollowed",
            "success" : True
        })

    if request.method == "POST":
        with get_database() as client:
            client.database.get_collection("follows").update_one({"user_id": discord_id, "follow_id" : int(follow_id)}, {
                "$set": {
                    "user_id": discord_id,
                    "followed_on": datetime.now(),
                    "follow_id": int(follow_id)
                }
            }, upsert=True)
        
        return dumps({
            "message" : "Followed",
            "success" : True
        })

    if request.method == "GET":
        with get_database() as client:
            follow = client.database.get_collection("follows").find_one({"user_id": discord_id, "follow_id" : int(follow_id)})
            if follow:
                following = True
            else:
                following = False
        
        return dumps({"following": following})

def pulse(agent_id):
    with get_database() as client:
        agentCollection = client.database.get_collection("agents")
        agentCollection.update_one({"agent_id": agent_id}, {"$set": {"last_seen": datetime.now()}})


def user_pulse(author_id):
    with get_database() as client:
        agentCollection = client.database.get_collection("users")
        agentCollection.update_one({"user_id": author_id}, {"$set": {"last_seen": datetime.now()}}, upsert=True)


@app.route("/recent/<amount>", methods=["GET"], defaults={"page": 1})
@app.route("/recent/<amount>/<page>")
def recent_images2(amount, page):
    with get_database() as client:
        r = client.database.get_collection("queue").aggregate(
            [
                {"$match": {"status": "archived", "nsfw": {"$ne": "yes"}, "render_type": {"$ne": "sketch"}}},
                {"$addFields": {"str_timestamp": {"$toString": "$timestamp"}}},
                {"$addFields": {"dt_timestamp": {"$dateFromString": {"dateString": "$str_timestamp"}}}},
                {"$sort": {"dt_timestamp": -1}},
                {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)},
                {"$unwind": "$userdets"},
                {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
            ]
        )
        return dumps(r)


@app.route("/random/<amount>", defaults={"shape": None})
@app.route("/random/<amount>/<shape>")
def random_images(amount, shape):
    q = {"status": "archived", "nsfw": {"$ne": "yes"}}
    if shape is not None:
        q["shape"] = shape

    with get_database() as client:
        r = client.database.get_collection("queue").aggregate(
            [
                {"$match": q},
                {"$sample": {"size": int(amount)}},
                {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
                {"$unwind": "$userdets"},
                {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
            ]
        )
        return dumps(r)


@app.route("/userfeed/<user_id>/<amount>", methods=["GET"], defaults={"page": 1})
@app.route("/userfeed/<user_id>/<amount>/<page>")
def userfeed(user_id, amount, page):
    with get_database() as client:
        r = client.database.get_collection("queue").aggregate(
            [
                {
                    "$addFields": {"author_id": {"$toLong": "$author"}},
                },
                {"$addFields": {"str_timestamp": {"$toString": "$timestamp"}}},
                {"$addFields": {"dt_timestamp": {"$dateFromString": {"dateString": "$str_timestamp"}}}},
                {"$match": {"status": "archived", "author_id": int(user_id), "nsfw": {"$ne": "yes"}}},
                {"$sort": {"dt_timestamp": -1}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)},
                {"$lookup": {"from": "users", "localField": "author_id", "foreignField": "user_id", "as": "userdets"}},
                {"$unwind": "$userdets"},
                {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
            ]
        )
        return dumps(r)


@app.route("/getsince/<seconds>", methods=["GET"])
def getsince(seconds):
    since = datetime.now() - timedelta(seconds=int(seconds))
    q = {"status": "archived", "last_preview": {"$gt": since}}
    with get_database() as client:
        query = {"$query": q, "$orderby": {"timestamp": -1}}
        queue = client.database.get_collection("queue").find(query)
        return dumps(queue)


@app.route("/web/up_next", methods=["GET"])
def up_next():
    with get_database() as client:
        up_next = list(client.database.vw_next_up.find({}))
        return dumps(up_next)

@app.route("/web/queue/", methods=["GET"], defaults={"status": "all"})
@app.route("/web/queue/<status>/")
def web_queue(status):
    logger.info(f"Queue request for status {status}...")
    if status == "stalled":
        since = datetime.now() - timedelta(minutes=BOT_STALL_TIMEOUT)
        q = {"status": "processing", "$or": [{"last_preview": {"$lt": since}}, {"last_preview": {"$exists": False}, "timestamp": {"$lt": since}}]}
    else:
        q = {"status": {"$nin": ["archived", "rejected"]}}
    # if who == "me":
    #     q["author"] = int(author)
    if status != "all" and status != "stalled":
        q["status"] = status
    # if status == "all" and who=="me":
    #     del q["status"]
    with get_database() as client:
        query = {"$query": q, "$orderby": {"timestamp": -1}}
        # queue = client.database.get_collection("queue").find(query)
        queue = client.database.sanitized_jobs.aggregate(
            [
                {"$match": q},
                {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
                {"$unwind": "$userdets"},
                {"$unwind": "$uuid"},
                {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
            ]
        )
        return dumps(queue)


@app.route("/queue/", methods=["GET"], defaults={"status": "all"})
@app.route("/queue/<status>/")
def queue(status):
    logger.info(f"Queue request for status {status}...")
    if status == "stalled":
        since = datetime.now() - timedelta(minutes=BOT_STALL_TIMEOUT)
        q = {"status": "processing", "$or": [{"last_preview": {"$lt": since}}, {"last_preview": {"$exists": False}, "timestamp": {"$lt": since}}]}
    else:
        q = {"status": {"$nin": ["archived", "rejected"]}}
    # if who == "me":
    #     q["author"] = int(author)
    if status != "all" and status != "stalled":
        q["status"] = status
    # if status == "all" and who=="me":
    #     del q["status"]
    with get_database() as client:
        n = datetime.now()
        query = {"$query": q, "$orderby": {"timestamp": -1}}
        queue = client.database.get_collection("queue").find(query)
        # queue = client.database.get_collection("queue").aggregate( [
        #         {"$match" : q},
        #     {"$lookup" : {
        #         "from":"users",
        #         "localField" : "author",
        #         "foreignField" : "user_id",
        #         "as" : "userdets"
        #     }},
        #     {"$unwind": "$userdets"},
        #     {"$unwind": "$uuid"},
        #     { "$addFields" :{
        #         "userdets.user_str": {"$toString": "$userdets.user_id"}
        #     }
        # }
        # ])
        e = datetime.now()
        t = e - n
        logger.info(f"{t} seconds elapsed")
        return dumps(queue)


@app.route("/events/", methods=["GET"], defaults={"status": "new"})
@app.route("/events/<status>/")
def events(status):
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    q = {"ack": False}
    if status == "new":
        q = {"ack": False}
    query = {"$query": q, "$orderby": {"timestamp": 1}}
    with get_database() as client:
        events = client.database.get_collection("events").find(query)
        return dumps(events)


@app.route("/logs/")
def logs():
    q = {"ack": False}
    query = {"$query": q, "$orderby": {"timestamp": 1}}
    with get_database() as client:
        logs = client.database.get_collection("logs").find(query)
        return dumps(logs)


@app.route("/ack_event/<uuid>/")
def ack_event(uuid):
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    logger.info(f"Acknowledging event '{uuid}'")
    with get_database() as client:
        result = client.database.get_collection("events").delete_one({"uuid": uuid})
        logger.info(f"Deleted {uuid} ({result.deleted_count})")
        return dumps({"deleted_count": result.deleted_count})


@app.route("/ack_log/<uuid>/")
def ack_log(uuid):
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    logger.info(f"Acknowledging log '{uuid}'")
    with get_database() as client:
        result = client.database.get_collection("logs").update_one({"uuid": uuid}, {"$set": {"ack": True}})
        logger.info(f"Acknowledged {uuid} ({result.modified_count})")
        return dumps({"modified_count": result.modified_count})


@app.route("/dreams", methods=["GET"])
def dreams():
    with get_database() as client:
        dreams = client.database.get_collection("userdreams").find({"$query": {}, "$orderby": {"count": 1}})
        return dumps(dreams)


@app.route("/takedream", methods=["GET"])
def takedream():
    dream = getOldestDream()
    return dumps(dream)


def getOldestDream():
    with get_database() as client:
        dreamCollection = client.database.get_collection("userdreams")
        # Get oldest dream
        dream = dreamCollection.find_one(
            {
                "$query": {
                    "dream": {"$exists": True},
                    # "author_id" : {"$ne": 823976252154314782}
                    # "$or" : [
                    #     {"count":{"$lt": 30}},
                    #     {"count":{"$exists": False}}
                    # ]
                },
                "$orderby": {"count": 1},
            }
        )
        if dream:
            if dream.get("count"):
                count = int(dream.get("count")) + 1
            else:
                count = 1
            dreamCollection.update_one({"author_id": dream.get("author_id")}, {"$set": {"last_used": datetime.now(), "count": count}}, upsert=True)
            return dream
        else:
            logger.info("no dream")
            return None


@app.route("/awaken/<author_id>", methods=["GET"])
def awaken(author_id):
    with get_database() as client:
        dreamCollection = client.database.get_collection("userdreams")
        dreamCollection.delete_many({"dream": {"$exists": False}})
        dreamCollection.delete_one({"author_id": int(author_id)})
        return dumps({"message": f"Dream for {author_id} deleted."})

@app.route("/prioritize/<job_uuid>", methods=["GET"])
def prioritize(job_uuid):
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        queueCollection.update_one({"uuid": job_uuid}, {"$set" : {"priority" : True}})
        return dumps({"message": f"Job {job_uuid} prioritized."})


@app.route("/serverinfo", methods=["POST"])
def serverinfo_post():
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    with get_database() as client:
        postsCollection = client.database.get_collection("serverposts")
        doc = {"subject": request.form.get("subject"), "channel": int(request.form.get("channel")), "message": int(request.form.get("message")), "timestamp": str(datetime.now())}
        logger.info(doc)
        postsCollection.update_one({"subject": request.form.get("subject")}, {"$set": doc}, upsert=True)
        return jsonify({"message": "ok"})


@app.route("/serverinfo/<subject>", methods=["GET"])
def serverinfo(subject):
    with get_database() as client:
        postsCollection = client.database.get_collection("serverposts")
        post = postsCollection.find_one({"subject": subject})
        return dumps(post)


@app.route("/nsfw", methods=["GET"])
def nsfw():
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        post = queueCollection.update_many({"render_type": "nightmare"}, {"$set": {"nsfw": "yes"}})
        return "ok"


@app.route("/private", methods=["GET"])
@requires_auth
def private():
    logger.info(f"Dreams from {discord_id}...")
    return jsonify(_request_ctx_stack.top.current_user)


@app.route("/web/dream", methods=["POST", "GET"])
@requires_auth
def webdream():
    current_user = _request_ctx_stack.top.current_user
    discord_id = current_user["sub"].split("|")[2]

    if request.method == "GET":
        with get_database() as client:
            dreamCollection = client.database.get_collection("userdreams")
            dream = dreamCollection.find_one({"author_id": int(discord_id)})
            return dumps(dream)

    if request.method == "POST":
        with get_database() as client:
            dreamCollection = client.database.get_collection("userdreams")

            dreamCollection.update_one(
                {"author_id": int(discord_id)},
                {
                    "$set": {
                        "author_id": int(discord_id),
                        "dream": request.json.get("dream"),
                        "is_nightmare": request.json.get("is_nightmare"),
                        "count": 0,
                        "last_used": datetime.now(),
                        "timestamp": datetime.now(),
                    }
                },
                upsert=True,
            )
            return dumps({"success": True})


@app.route("/dream", methods=["POST", "GET"])
def dream():
    if request.method == "POST":
        if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
            return jsonify({"message": "ERROR: Unauthorized"}), 401
        with get_database() as client:
            dreamCollection = client.database.get_collection("userdreams")
            dreamCollection.update_one(
                {"author_id": request.form.get("author_id", type=int)},
                {
                    "$set": {
                        "author_id": request.form.get("author_id", type=int),
                        "dream": request.form.get("dream"),
                        "count": 0,
                        "is_nightmare": request.form.get("is_nightmare"),
                        "last_used": datetime.now(),
                        "timestamp": datetime.now(),
                    }
                },
                upsert=True,
            )

        logger.info(request.form.get("dream"))
        return jsonify({"message": "received"})
    if request.method == "GET":
        with get_database() as client:
            dreamCollection = client.database.get_collection("userdreams")
            dream = dreamCollection.find_one({"author_id", request.form.get("user", type=int)})
            return jsonify(dream)


@app.route("/users")
def users():
    with get_database() as client:
        userCollection = client.database.get_collection("users")
        users = userCollection.find({})
        # logger.info(users)
        return dumps(users)

@app.route("/user/<user_id>", methods=["GET"])
def user(user_id):
    with get_database() as client:
        userCollection = client.database.vw_users
        logger.info(f"🔍 {int(user_id)}")
        user = userCollection.find_one({ "user_id_str" : user_id})
        logger.info(user)
        return dumps(user)

@app.route("/updateuser", methods=["POST"])
def updateuser():
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    user_id = request.form.get("user_id", type=int)
    user_name = request.form.get("user_name")
    with get_database() as client:
        userCollection = client.database.get_collection("users")
        userCollection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_name": user_name,
                    "display_name": request.form.get("display_name"),
                    "discriminator": request.form.get("discriminator"),
                    "nick": request.form.get("nick"),
                    "avatar": request.form.get("avatar"),
                }
            },
            upsert=True,
        )
    return dumps({"success": True})


@app.route("/abandonjob/<agent_id>", methods=["GET"])
def abandonjob(agent_id):
    with get_database() as client:
        result = client.database.get_collection("queue").update_many({"agent_id": agent_id, "status":"processing"}, {"$set": {
            "status": "queued", "agent_id": None, "percent": None, "last_preview": None
        }})
        logger.info(f"Abandoned ({result.matched_count})")
        return({"success": True})


@app.route("/updatejob", methods=["POST"])
def updatejob():
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    uuid = request.form.get("uuid")
    # logger.info(f"Updating job '{uuid}'")
    vals = request.form
    newvals = {}
    for val in vals:
        newvals[val] = vals[val]
        if val == "last_preview":
            newvals[val] = datetime.strptime(vals[val], "%Y-%m-%d %H:%M:%S.%f")
    with get_database() as client:
        result = client.database.get_collection("queue").update_one({"uuid": uuid}, {"$set": newvals})
        logger.info(f"Updated {uuid} ({result.matched_count})")
        return dumps({"matched_count": result.matched_count})


@app.route("/query/<job_uuid>", methods=["GET"])
def query(job_uuid):
    with get_database() as client:
        queueCollection = client.database.sanitized_jobs
        job = queueCollection.find_one({"uuid": job_uuid})
        opts = jsbeautifier.default_options()
        opts.indent_size = 2
        return jsonify(json.loads(dumps(job)))


@app.route("/rejects", methods=["GET"])
def rejects():
    with get_database() as client:
        queue = client.database.sanitized_jobs.find({"$query": {"status": "rejected"}, "$orderby": {"timestamp": -1}})
        return dumps(queue)


@app.route("/myhistory/<author_id>", methods=["GET"], defaults={"status": "all"})
@app.route("/myhistory/<author_id>/<status>", methods=["GET"])
def myhistory(author_id, status):
    author_qry = [{"author": int(author_id)}, {"author": str(author_id)}]
    if status == "all":
        q = {"$or": author_qry}
    else:
        q = {"$or": author_qry, "status": status}
    with get_database() as client:
        queueCollection = client.database.sanitized_jobs
        jobs = queueCollection.find(q)
        return jsonify(json.loads(dumps(jobs)))

@app.route("/job/<job_uuid>", methods=["GET", "DELETE"])
def job(job_uuid):
    if request.method == "GET":
        logger.info(f"Accessing {job_uuid}...")
        with get_database() as client:
            queueCollection = client.database.sanitized_jobs
            jobs = queueCollection.aggregate(
                [
                    {"$match": {"uuid": job_uuid}},
                    {"$addFields": {"author_bigint": {"$toLong": "$author"}}},
                    {"$lookup": {"from": "vw_users", "localField": "author_bigint", "foreignField": "user_id", "as": "userdets"}},
                    {"$unwind": "$userdets"},
                    {"$unwind": "$uuid"},
                    {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
                ]
            )
            jobs = list(jobs)
            if len(jobs) == 0:
                return dumps(None)
            try:
                views = jobs[0]["views"]
            except:
                views = 0
            logger.info(jobs[0])
            # views = job[0].get("views")
            # if not views:
            #     views = 0
            views += 1
            client.database.queue.update_one({"uuid": job_uuid}, {"$set": {"views": views}}, upsert=True)
            jobs[0]["views"] = views
            return dumps(jobs[0])
    if request.method == "DELETE":
        if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
            return jsonify({"message": "ERROR: Unauthorized"}), 401
        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            d = queueCollection.delete_many({"uuid": job_uuid})
            return dumps({"deleted_count": d.deleted_count})


@app.route("/duplicate/<job_uuid>", methods=["GET"])
def duplicate(job_uuid):
    if request.method == "GET":
        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            job = queueCollection.find_one({"uuid": job_uuid}, {"_id": 0})
            return dumps(job)


@app.route("/agentstats")
def agent():
    with get_database() as client:
        since = datetime.now() - timedelta(minutes=10)
        agents = client.database.get_collection("agents").find({"last_seen": {"$gt": since}}).sort("last_seen", -1)
        return dumps(agents)

@app.route("/agent/<agent_id>")
def agentstats(agent_id):
    with get_database() as client:
        agent = client.database.get_collection("agents").find_one({"agent_id": agent_id})
        return dumps(agent)


@app.route("/queuestats")
def queuestats():
    n = datetime.now()
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        queuedCount = queueCollection.count_documents({"status": "queued"})
        processingCount = queueCollection.count_documents({"status": "processing"})
        renderedCount = queueCollection.count_documents({"status": "archived"})
        completedCount = queueCollection.count_documents({"status": "complete"})
        rejectedCount = queueCollection.count_documents({"status": "rejected"})
        e = datetime.now()
        t = e - n
        logger.info(f"{t} seconds elapsed in queuestats call")
        return dumps(
            {"queuedCount": queuedCount, "processingCount": processingCount, "renderedCount": renderedCount, "rejectedCount": rejectedCount, "completedCount": completedCount}
        )


@app.route("/cancel/<job_uuid>", methods=["DELETE"])
def cancel(job_uuid):
    if request.method == "DELETE":
        if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
            return jsonify({"message": "ERROR: Unauthorized"}), 401

        with get_database() as client:
            q = {"author": request.form.get("requestor", type=int), "uuid": job_uuid, "status": "queued"}
            logger.info(q)
            result = client.database.get_collection("queue").delete_many(q)
            count = result.deleted_count

        if count == 0:
            return dumps({"message": f"❌ Could not delete job `{job_uuid}`.  Check the Job ID and if you are the owner, and that your job has not started running yet."})
        else:
            return dumps({"message": f"🗑️ Job `{job_uuid}` removed."})


@app.route("/config/<job_uuid>", methods=["GET"])
def config(job_uuid):
    try:
        filename = f"{job_uuid}_gen.yaml"
        fn = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        return send_file(fn, mimetype="text/yaml")
    except:
        return f"Could not locate {filename}.  This might be because the render has not completed yet.  Or because Mike sucks."


def serve_pil_image(pil_img):
    img_io = BytesIO()
    pil_img.save(img_io, "JPEG", quality=70)
    img_io.seek(0)
    return send_file(img_io, mimetype="image/jpeg")


def s3_jpg(job_uuid):
    try:
        try:
            url = f"{BOT_S3_WEB}{job_uuid}0_0.png"
            img = Image.open(urlopen(url))
        except:
            url = f"{BOT_S3_WEB}{job_uuid}_progress.png"
            img = Image.open(urlopen(url))

        jpgfile = f"{job_uuid}.jpg"
        img.save(jpgfile, "JPEG")
        upload_file_s3(jpgfile, BOT_S3_BUCKET, f"jpg/{job_uuid}.jpg", {"ContentType": "image/jpeg"})
        os.remove(jpgfile)
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        return f"Could not locate {url}.  This might be because the render has not completed yet.  Or because the job failed.  Or check your job uuid.  Or a gremlin ate the image.  Probably the gremlin.\n{tb}"

def algolia_index(job_uuid):
    from algoliasearch.search_client import SearchClient
    # Start the API client
    # https://www.algolia.com/doc/api-client/getting-started/instantiate-client-index/
    client = SearchClient.create(ALGOLIA_APP_ID, ALGOLIA_API_KEY)
    # Create an index (or connect to it, if an index with the name `ALGOLIA_INDEX_NAME` already exists)
    # https://www.algolia.com/doc/api-client/getting-started/instantiate-client-index/#initialize-an-index
    index = client.init_index(ALGOLIA_INDEX_NAME)

    with get_database() as client:
        job = client.database.sanitized_jobs.find_one({"uuid": job_uuid})
        new_object = {"objectID": job_uuid, "uuid": job_uuid, "text_prompt": job.get("text_prompt")}
        res = index.save_objects([new_object])
        res.wait()

def s3_thumbnail(job_uuid, size):
    try:
        try:
            url = f"{BOT_S3_WEB}{job_uuid}0_0.png"
            img = Image.open(urlopen(url))
        except:
            url = f"{BOT_S3_WEB}{job_uuid}_progress.png"
            img = Image.open(urlopen(url))

        img.thumbnail((int(size), int(size)), Image.LANCZOS)
        thumbfile = f"thumb_{size}_{job_uuid}.jpg"
        img.save(thumbfile, "JPEG")
        upload_file_s3(thumbfile, BOT_S3_BUCKET, f"thumbs/{size}/{job_uuid}.jpg", {"ContentType": "image/jpeg"})
        os.remove(thumbfile)
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        return f"Could not locate {url}.  This might be because the render has not completed yet.  Or because the job failed.  Or check your job uuid.  Or a gremlin ate the image.  Probably the gremlin.\n{tb}"


# @app.route("/thumbnail/<job_uuid>", methods=["GET"], defaults={"size": 128})
# @app.route("/thumbnail/<job_uuid>/<size>", methods=["GET"])
# def thumbnail(job_uuid, size):
#     try:
#         try:
#             url = f"{BOT_S3_WEB}{job_uuid}0_0.png"
#             img = Image.open(urlopen(url))
#         except:
#             url = f"{BOT_S3_WEB}{job_uuid}_progress.png"
#             img = Image.open(urlopen(url))
#         img.thumbnail((int(size), int(size)), Image.ANTIALIAS)
#         return serve_pil_image(img)
#     except Exception as e:
#         import traceback

#         tb = traceback.format_exc()
#         return f"Could not locate {url}.  This might be because the render has not completed yet.  Or because the job failed.  Or check your job uuid.  Or a gremlin ate the image.  Probably the gremlin.\n{tb}"


@app.route("/local/thumbnail/<job_uuid>", methods=["GET"], defaults={"size": 128})
@app.route("/local/thumbnail/<job_uuid>/<size>", methods=["GET"])
def local_thumbnail(job_uuid, size):
    try:
        filename = f"{job_uuid}0_0.png"
        fn = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        img = Image.open(fn)
        img.thumbnail((int(size), int(size)), Image.ANTIALIAS)
        return serve_pil_image(img)
    except Exception as e:
        return f"Could not locate {filename}.  This might be because the render has not completed yet.  Or because the job failed.  Or check your job uuid.  Or a gremlin ate the image.  Probably the gremlin.\n{e}"


# @app.route("/image/<job_uuid>", methods=["GET"])
# def image(job_uuid):
#     try:
#         filename = f"{job_uuid}0_0.png"
#         fn = os.path.join(app.config["UPLOAD_FOLDER"], filename)
#         from os.path import exists

#         if not exists(fn):
#             filename = f"{job_uuid}_progress.png"
#             fn = os.path.join(app.config["UPLOAD_FOLDER"], filename)

#         return send_file(fn, mimetype="image/png")
#     except:
#         return f"Could not locate {filename}.  This might be because the render has not completed yet.  Or because the job failed.  Or check your job uuid.  Or a gremlin ate the image.  Probably the gremlin."


@app.route("/reject/<agent_id>/<job_uuid>", methods=["POST"])
def reject(agent_id, job_uuid):
    pulse(agent_id=agent_id)
    logger.error(f"rejecting {job_uuid}")
    tb = request.form.get("traceback")
    log = request.form.get("log")
    logger.info(log)
    logger.info(tb)
    if request.method == "POST":
        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            results = queueCollection.update_one({"agent_id": agent_id, "uuid": job_uuid}, {"$set": {"status": "failed", "filename": None, "log": log, "traceback": tb}})
            count = results.modified_count
        if count == 0:
            return f"cannot find that job."
        else:
            return f"job rejected, {agent_id}."


@app.route("/uploadlog/<agent_id>/<job_uuid>", methods=["POST"])
def upload_log(agent_id, job_uuid):
    file = request.files["file"]
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)
    if BOT_USE_S3:
        try:
            upload_file_s3(filepath, BOT_S3_BUCKET, f"images/{filename}")
        except Exception as e:
            logger.error(e)

    with open(os.path.join(app.config["UPLOAD_FOLDER"], filename), "r") as f:
        run_log = f.read()

    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        results = queueCollection.update_one({"agent_id": agent_id, "uuid": job_uuid}, {"$set": {"log": filename}})
        count = results.modified_count
        if count == 0:
            return f"cannot find that job."
        else:
            return "Log uploaded."


@app.route("/uploadconfig/<agent_id>/<job_uuid>", methods=["POST"])
def upload_config(agent_id, job_uuid):
    file = request.files["file"]
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)
    if BOT_USE_S3:
        try:
            upload_file_s3(filepath, BOT_S3_BUCKET, f"images/{filename}")
        except Exception as e:
            logger.error(e)
    
    # Store YAML results as JSON in job document
    with open(os.path.join(app.config["UPLOAD_FOLDER"], filename), "r") as f:
        contents = f.read()
        confargs = pydot(full_load(contents))
        logger.info(f"🪵 Processing {job_uuid} YAML...")
        with get_database() as client:
            client.database.get_collection("queue").update_one({"uuid": job_uuid}, {"$set": {"results": confargs}})

    # Legacy
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        results = queueCollection.update_one({"agent_id": agent_id, "uuid": job_uuid}, {"$set": {"config": filename}})
        count = results.modified_count
        if count == 0:
            return f"cannot find that job."
        else:
            return "Config uploaded."


@app.route("/progress/<agent_id>/<job_uuid>", methods=["GET", "POST"])
def progress(agent_id, job_uuid):
    pulse(agent_id=agent_id)
    if request.method == "POST":
        gpustats = request.form.get("gpustats")
        if gpustats:
            try:
                memory = int(gpustats.split(", ")[4])
            except:
                memory = 0
        else:
            memory = 0
        e = {"type": "progress", "agent": agent_id, "job_uuid": job_uuid, "percent": request.form.get("percent"), "gpustats": gpustats}
        event(e)
        # logger.info(e)
        with get_database() as client:
            agentCollection = client.database.get_collection("agents")
            agentCollection.update_one({"agent_id": agent_id}, {"$set": {"gpustats": gpustats}})
            queueCollection = client.database.get_collection("queue")
            job = queueCollection.find_one({"uuid": job_uuid})
            hwm = 0
            if job:
                # Calc high watermark in memory
                if job.get("mem_hwm"):
                    hwm = int(job.get("mem_hwm"))
                    if memory > hwm:
                        hwm = memory
                else:
                    hwm = memory
            # logger.info(f"{hwm} - {memory}")
            results = queueCollection.update_one({"agent_id": agent_id, "uuid": job_uuid}, {"$set": {"percent": request.form.get("percent"), "mem_hwm": hwm}})
            count = results.modified_count
            if count == 0:
                return f"cannot find that job."
            else:
                return "Log uploaded."

    if request.method == "GET":
        return "OK"


@app.route("/preview/<agent_id>/<job_uuid>", methods=["GET", "POST"])
def preview_file(agent_id, job_uuid):
    pulse(agent_id=agent_id)
    if request.method == "POST":
        file = request.files["file"]
        if file.filename == "":
            flash("No file uploaded.")
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], f"{job_uuid}_{filename}")
            file.save(filepath)
            logger.info(f"{job_uuid}_{filename} saved.")
            if BOT_USE_S3:
                try:
                    upload_file_s3(filepath, BOT_S3_BUCKET, f"images/{job_uuid}_{filename}", {"ContentType": "image/png"})
                    logger.info(f"{job_uuid}_{filename} saved to s3.")
                except Exception as e:
                    logger.error(e)
            e = {"type": "preview", "agent": agent_id, "job_uuid": job_uuid}
            event(e)
            with get_database() as client:
                queueCollection = client.database.get_collection("queue")
                queueCollection.update_one({"agent_id": agent_id, "uuid": job_uuid}, {"$set": {"preview": True}})
            return f"{job_uuid}_filename"
        else:
            return "Bad file."


@app.route("/upload/<agent_id>/<job_uuid>", methods=["GET", "POST"])
def upload_file(agent_id, job_uuid):
    pulse(agent_id=agent_id)
    if request.method == "POST":
        logger.info(request.form.get("duration"))
        if request.form.get("duration"):
            duration = float(request.form.get("duration"))
        else:
            duration = 0.0
        # check if the post request has the file part
        if "file" not in request.files:
            flash("No file part")
            return redirect(request.url)
        file = request.files["file"]
        # If the user does not select a file, the browser submits an
        # empty file without a filename.
        if file.filename == "":
            flash("No file uploaded.")
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            logger.info(f"🎨 Analyzing colors for {job_uuid}...")
            color_thief = ColorThief(filepath)
            dominant_color = color_thief.get_color(quality=1)
            palette = color_thief.get_palette(color_count=5)
            logger.info(f"🎨 Color analysis for {job_uuid} complete.")
            with get_database() as client:
                client.database.get_collection("queue").update_one({"uuid": job_uuid}, {"$set": {"dominant_color": dominant_color, "palette": palette}})
            
            try:
                algolia_index(job_uuid)
                with get_database() as client:
                    client.database.get_collection("queue").update_one({"uuid": job_uuid}, {"$set": {"indexed": True}})
                    logger.info(f"🔍 Job indexed to Algolia.")
            except:
                logger.info("Error trying to submit Algolia index.")
                pass

            if BOT_USE_S3:
                try:
                    upload_file_s3(filepath, BOT_S3_BUCKET, f"images/{filename}", {"ContentType": "image/png"})
                    s3_thumbnail(job_uuid, 64)
                    s3_thumbnail(job_uuid, 128)
                    s3_thumbnail(job_uuid, 256)
                    s3_thumbnail(job_uuid, 512)
                    s3_thumbnail(job_uuid, 1024)
                    with get_database() as client:
                        client.database.get_collection("queue").update_one({"uuid": job_uuid}, {"$set": {"thumbnails": [64, 128, 256, 512, 1024]}})
                        logger.info(f"👍 Thumbnails uploaded to s3 for {job_uuid}")

                    s3_jpg(job_uuid)
                    with get_database() as client:
                        client.database.get_collection("queue").update_one({"uuid": job_uuid}, {"$set": {"jpg": True}})
                        logger.info(f"🖼️ JPEG version for {job_uuid} saved to s3")

                except Exception as e:
                    logger.error(e)
            with get_database() as client:
                queueCollection = client.database.get_collection("queue")
                results = queueCollection.update_one(
                    {"agent_id": agent_id, "uuid": job_uuid}, {"$set": {"status": "complete", "filename": filename, "duration": duration, "percent": 100}}
                )
                count = results.modified_count
            if count == 0:
                return f"cannot find that job."
            else:
                with get_database() as client:
                    agentCollection = client.database.get_collection("agents")
                    results = agentCollection.find_one({"agent_id": agent_id})
                    score = results.get("score")
                    if not score:
                        score = 1
                    else:
                        score += 1
                    results = agentCollection.update_one({"agent_id": agent_id}, {"$set": {"score": score}})
                    return f"thank you, {agent_id}."
        else:
            return "Bad file."
    else:
        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            count = queueCollection.count_documents({"uuid": job_uuid, "status": "processing"})
        if count == 1:
            return """
            <!doctype html>
            <title>Upload new File</title>
            <h1>Upload new File</h1>
            <form method=post enctype=multipart/form-data>
            <input type=file name=file>
            <input type=submit value=Upload>
            </form>
            """
        else:
            return f"""
            <!doctype html>
            <title>Upload new File</title>
            <h1>Error</h1>
            We are not expecting an upload from agent {agent_id} for job {job_uuid}.
            """


@app.route("/")
def base():
    return redirect(BOT_WEBSITE, code=302)


@app.route("/clearlogs")
def clearlogs():
    with get_database() as client:
        logCollection = client.database.get_collection("logs")
        logCollection.drop()
    return "dropped logs"


@app.route("/retryall")
def retryall():
    with get_database() as client:
        result = client.database.get_collection("queue").update_many({"status": "rejected"}, {"$set": {"status": "queued"}})
    return "retrying all"


@app.route("/clearevents")
def clearevents():
    with get_database() as client:
        logCollection = client.database.get_collection("events")
        logCollection.drop()
    return "dropped events"

@app.route("/web/profile", methods=["POST"])
@requires_auth
def web_profile():
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    profile = request.json.get("profile")
    with get_database() as client:
        client.database.users.update_one({"user_id": discord_id}, {"$set" : {"social" : profile["social"]}})
    return dumps({"success" : True})

@app.route("/web/mutate", methods=["POST"])
@requires_auth
def web_mutate():
    # TODO: Rewrite this
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    logger.info(f"Incoming mutation job request from {discord_id}...")
    job = request.json.get("job")
    experimental = False
    try:
        experimental = job["experimental"]
    except:
        pass
    try:
        sym = job["symmetry"]
    except:
        sym = "no"
    try:
        sls = job["symmetry_loss_scale"]
    except:
        sls = 0
    try:
        eta = job["eta"]
    except:
        eta = 0.8
    try:
        shape = job["shape"]
    except:
        shape = "landscape"
    try:
        model = job["model"]
    except:
        model = "default"
    try:
        diffusion_model = job["diffusion_model"]
    except:
        diffusion_model = "512x512_diffusion_uncond_finetune_008100"
    try:
        cut_schedule = job["cut_schedule"]
    except:
        cut_schedule = "default"
    try:
        clip_guidance_scale = job["clip_guidance_scale"]
    except:
        clip_guidance_scale = 5000
    try:
        cut_ic_pow = job["cut_ic_pow"]
    except:
        cut_ic_pow = 1
    try:
        clamp_max = job["clamp_max"]
    except:
        clamp_max = 0.05
    try:
        sat_scale = job["sat_scale"]
    except:
        sat_scale = 0
    try:
        cutn_batches = job["cutn_batches"]
    except:
        cutn_batches = 4
    try:
        nsfw = job["nsfw"]
    except:
        nsfw = "no"

    newrecord = {
        "uuid": str(uuid.uuid4()),
        "experimental" : experimental,
        "parent_uuid": job["uuid"],
        "render_type": "mutate",
        "text_prompt": job["text_prompt"],
        "steps": job["steps"],
        "shape": shape,
        "model": model,
        "diffusion_model": diffusion_model,
        "symmetry": sym,
        "symmetry_loss_scale": sls,
        "cut_schedule": cut_schedule,
        "clip_guidance_scale": clip_guidance_scale,
        "clamp_max": clamp_max,
        "set_seed": job["set_seed"],
        "cut_ic_pow": cut_ic_pow,
        "cutn_batches": cutn_batches,
        "sat_scale": sat_scale,
        "nsfw": nsfw,
        "author": discord_id,
        "status": "queued",
        "eta": eta,
        "timestamp": str(datetime.utcnow()),
        "origin": "web"
    }
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        queueCollection.insert_one(newrecord)
    user_pulse(discord_id)
    return dumps({"success" : True, "new_record" : newrecord})

@app.route("/placeorder", methods=["POST"])
def placeorder():
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    author = request.form.get("author", type=int)
    newrecord = {
        "uuid": request.form.get("uuid", type=str),
        "parent_uuid": request.form.get("parent_uuid", type=str),
        "render_type": request.form.get("render_type"),
        "text_prompt": request.form.get("text_prompt"),
        "steps": request.form.get("steps", type=int),
        "shape": request.form.get("shape"),
        "model": request.form.get("model"),
        "diffusion_model": request.form.get("diffusion_model"),
        "symmetry": request.form.get("symmetry"),
        "symmetry_loss_scale": request.form.get("symmetry_loss_scale", type=int),
        "cut_schedule": request.form.get("cut_schedule"),
        "clip_guidance_scale": request.form.get("clip_guidance_scale", type=int),
        "clamp_max": request.form.get("clamp_max", type=float),
        "set_seed": request.form.get("set_seed", type=int),
        "cut_ic_pow": request.form.get("cut_ic_pow", type=int),
        "cutn_batches": request.form.get("cutn_batches", type=int),
        "sat_scale": request.form.get("sat_scale", type=float),
        "nsfw": request.form.get("nsfw"),
        "author": author,
        "status": "queued",
        "eta": request.form.get("eta", type=float),
        "timestamp": str(datetime.utcnow()),
    }
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        queueCollection.insert_one(newrecord)
    user_pulse(author)
    return "ok"


@app.route("/search/<regexp>", methods=["GET"], defaults={"page": 1, "amount": 50})
@app.route("/search/<regexp>/<amount>", methods=["GET"], defaults={"page": 1})
@app.route("/search/<regexp>/<amount>/<page>", methods=["GET"])
def search(regexp, amount, page):
    with get_database() as client:
        j = client.database.get_collection("queue").aggregate(
            [
                {"$match": {"text_prompt": {"$regex": regexp, "$options": "i"}, "$or": [{"status": "processing"}, {"status": "complete"}, {"status": "archived"}]}},
                {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)},
                {"$unwind": "$userdets"},
            ]
        )
        return dumps(j)


@app.route("/rgb/<r>/<g>/<b>", methods=["GET"], defaults={"range": 5, "page": 1, "amount": 50})
@app.route("/rgb/<r>/<g>/<b>/<range>", methods=["GET"], defaults={"page": 1, "amount": 50})
@app.route("/rgb/<r>/<g>/<b>/<range>/<amount>", methods=["GET"], defaults={"page": 1})
@app.route("/rgb/<r>/<g>/<b>/<range>/<amount>/<page>", methods=["GET"])
def rgb(r, g, b, range, amount, page):
    with get_database() as client:
        j = client.database.get_collection("queue").aggregate(
            [
                {
                    "$match": {
                        "nsfw": {"$ne": "yes"},
                        "dominant_color.0": {"$gt": int(r) - int(range), "$lt": int(r) + int(range)},
                        "dominant_color.1": {"$gt": int(g) - int(range), "$lt": int(g) + int(range)},
                        "dominant_color.2": {"$gt": int(b) - int(range), "$lt": int(b) + int(range)},
                        "$or": [{"status": "complete"}, {"status": "archived"}],
                    }
                },
                {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)},
                {"$unwind": "$userdets"},
            ]
        )
        return dumps(j)


def facelift(job):
    try:
        if job["symmetry"] == "no":
            del job["symmetry"]
    except:
        pass

    return job

@app.route("/instructions/<agent_id>", methods=["GET","DELETE"])
def instructions(agent_id):
    if request.method == "DELETE":
        with get_database() as client:
            agentCollection = client.database.get_collection("agents")
            agent = agentCollection.update_one({"agent_id": agent_id}, {"$set" : {"instructions" : None}})
            logger.info("Instructions acknowledged.")
            return dumps({
                "success" : True,
                "message" : "Acknowledgement received"
            })
    if request.method == "GET":
        with get_database() as client:
            agentCollection = client.database.get_collection("agents")
            agent = agentCollection.find_one({"agent_id": agent_id})
            if not agent:
                logger.info(f"Unknown agent looking for work: {agent_id}")
                return dumps({"message": f"I don't know a {agent_id}.  Did you not register?", "success": False})
            else:
                if "instructions" in agent:
                    return dumps(agent["instructions"])
                else:
                    return dumps(None)

def postProcess(job_uuid):
    # Inspect Document results
    # https://docarray.jina.ai/fundamentals/document/
    from docarray import Document
    from docarray import DocumentArray
    import io, base64
    with get_database() as client:
        job = client.database.queue.find_one({"uuid": job_uuid})
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], job["filename"])
        
        # TODO: get rid of "0_0" suffix
        png = os.path.join(app.config["UPLOAD_FOLDER"], f"{job_uuid}0_0.png")
        da = DocumentArray.load_binary(filepath)
        da[0].save_uri_to_file(png)
        da_tags = da[0].tags
        logger.info(da_tags)
        # Annoyed that I can't figure this out.  Gonna write to filesystem
        # f = io.BytesIO(base64.b64decode(da[0].uri + '=='))
        
        ## Color Analysis
        color_thief = ColorThief(png)
        dominant_color = color_thief.get_color(quality=1)
        palette = color_thief.get_palette(color_count=5)
        client.database.queue.update_one({"uuid": job_uuid}, {"$set": {"dominant_color": dominant_color, "palette": palette}})
        logger.info(f"🎨 Color analysis for {job_uuid} complete.")

        ## Indexing to Algolia
        try:
            # TODO: Support array text_prompts
            algolia_index(job_uuid)
            client.database.get_collection("queue").update_one({"uuid": job_uuid}, {"$set": {"indexed": True}})
            logger.info(f"🔍 Job indexed to Algolia.")
        except:
            logger.info("Error trying to submit Algolia index.")
            pass
        
        ## Save thumbnails/jpg and upload to S3
        if BOT_USE_S3:
            try:
                # TODO: remove "0_0" suffix
                upload_file_s3(png, BOT_S3_BUCKET, f"images/{job_uuid}0_0.png", {"ContentType": "image/png"})
                s3_thumbnail(job_uuid, 64)
                s3_thumbnail(job_uuid, 128)
                s3_thumbnail(job_uuid, 256)
                s3_thumbnail(job_uuid, 512)
                s3_thumbnail(job_uuid, 1024)
                s3_jpg(job_uuid)
                client.database.get_collection("queue").update_one({"uuid": job_uuid}, {"$set": {"thumbnails": [64, 128, 256, 512, 1024], "jpg": True}})
                logger.info(f"👍 Thumbnails uploaded to s3 for {job_uuid}")
                logger.info(f"🖼️ JPEG version for {job_uuid} saved to s3")

            except Exception as e:
                logger.error(e)
        
        ## Mark as postprocessing complete
        results = client.database.queue.update_one(
            {"uuid": job_uuid}, {"$set": {"status": "complete", "time_completed" : datetime.now(), "discoart_tags" : da_tags, "results" : None}}
        )


@app.route("/v2/deliverorder", methods=["POST"])
def v2_deliver():
    agent_id = request.form.get("agent_id")
    agent_version = request.form.get("agent_version")
    job_uuid = request.form.get("uuid")

    if request.form.get("duration"):
        duration = float(request.form.get("duration"))
    else:
        duration = 0.0

    # check if the post request has the file part
    if "file" not in request.files:
        return dumps({
            "success" : False,
            "message" : "No file received."
        })
    file = request.files["file"]
    if file.filename == "":
        return dumps({
            "success" : False,
            "message" : "No file received."
        })

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
    else:
        return dumps({
            "success" : False,
            "message" : "Unexpected file type."
        })
    
    # Since payload is saved, update job record.
    with get_database() as client:
        client.database.queue.update_one(
            {"agent_id": agent_id, "uuid": job_uuid},
            {"$set": {
                "status" : "uploaded",
                "agent_version" : agent_version,
                "filename" : filename,
                "duration" : duration,
                "percent" : 100
            } }
        )
    
    # TODO: Post-processing
    try:
        postProcess(job_uuid)
        return dumps({
            "success" : True,
            "message" : "Delivery received!",
            "duration" : duration
        })
    except:
        import traceback
        tb = traceback.format_exc()
        logger.error(tb)
        return dumps({
            "success" : False,
            "message" : "Delivery failed!",
            "traceback" : tb
        })
@app.route("/v2/takeorder/<agent_id>", methods=["POST"])
def v2_takeorder(agent_id):
     # Make sure agent is registered...
    with get_database() as client:
        agent = client.database.agents.find_one({"agent_id": agent_id})
        if not agent:
            logger.info(f"Unknown agent looking for work: {agent_id}")
            return dumps({"message": f"I don't know a {agent_id}.  Did you not register?", "success": False})
        else:
            idle_time = request.form.get("idle_time")
            bot_version = request.form.get("bot_version")
            pulse(agent_id=agent_id)
            logger.info(f"{agent_id} looking for work - Idle time: {idle_time}...")
            mode = "awake"
            if int(idle_time) > 1800:
                mode = "dreaming"
            else:
                mode = "awake"
            with get_database() as client:
                client.database.agents.update_one({"agent_id": agent_id}, {"$set": {
                    "mode": mode,
                    "idle_time": int(idle_time),
                    "bot_version": str(bot_version)
                    }
                })
            logger.info(f"{agent_id} (version {str(bot_version)}) is {mode}, idle time {idle_time} seconds...")
            # Inform agent if there's already a job assigned...
        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            query = {
                "status": "processing",
                "agent_id": agent_id
            }
            jobCount = queueCollection.count_documents(query)
            if jobCount > 0:
                # Update status
                client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time": 0}})
                jobs = queueCollection.find_one(query)
                logger.info("working")
                return dumps({"message ": f"You already have a job.  (Job '{jobs.get('uuid')}')", "uuid": jobs.get("uuid"), "details": json.loads(dumps(facelift(jobs))), "success": True})
            else:
                # Check for priority jobs first
                query = {
                    "status": "queued",
                    "priority": True,

                }
                queueCount = queueCollection.count_documents(query)
                logger.info(f"{queueCount} priority jobs in queue.")
                # TODO: sketch logic
                if queueCount == 0:
                    query = {
                        "status": "queued"
                    }
                    up_next = list(client.database.vw_next_up.find({ "experimental" : True }))
                    queueCount = len(up_next)
                    logger.info(f"{queueCount} renders in queue.")
                    if queueCount > 0:
                        # Work found
                        job = up_next[0]
                        results = queueCollection.update_one({"uuid": job.get("uuid")}, {"$set": {"status": "processing", "agent_id": agent_id, "last_preview": datetime.now()}})
                        count = results.modified_count
                        if count > 0:
                            # Set initial progress
                            e = {"type": "progress", "agent": agent_id, "job_uuid": job.get("uuid"), "percent": 0, "gpustats": None}
                            event(e)
                            client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time": 0}})
                            return dumps({"message": f"Your current job is {job.get('uuid')}.", "uuid": job.get("uuid"), "details": json.loads(dumps(facelift(job))), "success": True})
                    else:
                        # No work, see if it's dream time:
                        logger.info("No user jobs in queue...")
                        if mode == "awake":
                            return dumps({"message": f"Could not secure a user job.", "success": False})
                        if mode == "dreaming":
                            logger.info("Dream Job incoming.")
                            d = dream(agent_id)
                            return dumps(d)

        return dumps({"message": f"No queued jobs at this time.", "success": False})
    return dumps(None)

@app.route("/takeorder/<agent_id>", methods=["POST"])
def takeorder(agent_id):
    if request.method == "POST":
        
        # Make sure agent is registered...
        with get_database() as client:
            agentCollection = client.database.get_collection("agents")
            agent = agentCollection.find_one({"agent_id": agent_id})
            if not agent:
                logger.info(f"Unknown agent looking for work: {agent_id}")
                return dumps({"message": f"I don't know a {agent_id}.  Did you not register?", "success": False})
        
        idle_time = request.form.get("idle_time")
        model = request.form.get("model")
        clip_models = request.form.get("clip_models")
        if clip_models:
            clip_models = json.loads(clip_models)
            logger.info(clip_models)
        else:
            clip_models = None
        bot_version = request.form.get("bot_version")
        if not bot_version:
            bot_version = "1.0"
        pulse(agent_id=agent_id)
        mode = "awake"
        if int(idle_time) > 30:
            mode = "dreaming"
        else:
            mode = "awake"
        
        # Update Agent status with current operation mode and idle time
        with get_database() as client:
            agentCollection = client.database.get_collection("agents")
            agentCollection.update_one({"agent_id": agent_id}, {"$set": {
                "mode": mode, 
                "model_mode": model,
                "clip_models": clip_models,
                "idle_time": int(idle_time),
                "bot_version": str(bot_version)
                }
            })
            logger.info(f"{agent_id} (version {str(bot_version)}) is {mode}, idle time {idle_time} seconds...")

        # Inform agent if there's already a job assigned...
        with get_database() as client:
            queueCollection = client.database.queue
            query = {"status": "processing", "agent_id": agent_id}
            jobCount = queueCollection.count_documents(query)
            if jobCount > 0:
                # Update status
                client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time": 0}})
                jobs = queueCollection.find_one(query)
                logger.info("working")
                return dumps({"message ": f"You already have a job.  (Job '{jobs.get('uuid')}')", "uuid": jobs.get("uuid"), "details": json.loads(dumps(facelift(jobs))), "success": True})
            else:
                # Check for priority jobs first
                query = {
                    "status": "queued",
                    "priority": True,
                    # HOTFIX
                    # "model": model,
                }
                queueCount = queueCollection.count_documents(query)
                logger.info(f"{queueCount} priority jobs in queue.")

                query = {
                    "status": "queued",
                    # "model": model,
                }
                up_next = list(client.database.vw_next_up.find({ "experimental" : { "$ne" : True }}))
                queueCount = len(up_next)
                logger.info(f"{queueCount} renders in queue.")

                if queueCount > 0:
                    # Work found
                    # job = queueCollection.find_one({"$query": query, "$orderby": {"timestamp": 1}})
                    job = up_next[0]

                    results = queueCollection.update_one({"uuid": job.get("uuid")}, {"$set": {"status": "processing", "agent_id": agent_id, "last_preview": datetime.now()}})
                    count = results.modified_count
                    if count > 0:
                        e = {"type": "progress", "agent": agent_id, "job_uuid": job.get("uuid"), "percent": 0, "gpustats": None}
                        event(e)
                        # log(f"Good news, <@{job.get('author')}>!  Your job `{job.get('uuid')}` is being processed now by `{agent_id}`...", title="💼 Job in Process")
                        agentCollection = client.database.get_collection("agents")
                        agentCollection.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time": 0}})
                        return dumps({"message": f"Your current job is {job.get('uuid')}.", "uuid": job.get("uuid"), "details": json.loads(dumps(facelift(job))), "success": True})
                else:
                    # Dream
                    logger.info("No user jobs in queue...")
                    if mode == "awake":
                        return dumps({"message": f"Could not secure a user job.", "success": False})
                    if mode == "dreaming":
                        logger.info("Dream Job incoming.")
                        d = dream(agent_id)
                        return dumps(d)

    return dumps({"message": f"No queued jobs at this time.", "success": False})


def dream(agent_id):
    import dd_prompt_salad

    job_uuid = uuid.uuid4()
    dream = getOldestDream()
    template = dream.get("dream")
    is_nightmare = dream.get("is_nightmare")
    if is_nightmare:
        render_type = "nightmare"
        nsfw = "yes"
    else:
        render_type = "dream"
        nsfw = "no"
    salad = dd_prompt_salad.make_random_prompt(amount=1, prompt_salad_path="prompt_salad", template=template)[0]
    text_prompt = salad
    logger.info(text_prompt)
    author_id = dream.get("author_id")
    import random

    shape = random.sample(["square", "pano", "landscape", "portrait"], 1)[0]
    model = random.sample(["default", "rn50x64", "vitl14", "vitl14x336"], 1)[0]
    steps = random.sample([200, 300], 1)[0]
    cut_ic_pow = random.sample([1, 5, 10], 1)[0]
    clip_guidance_scale = random.sample([5000, 7500, 10000, 15000, 20000], 1)[0]
    cutn_batches = random.sample([4, 6], 1)[0]
    cut_schedule = random.sample(["default", "detailed-a", "detailed-b"], 1)[0]
    sat_scale = random.sample([0, 0.5], 1)[0]
    with get_database() as client:
        job_uuid = str(job_uuid)
        record = {
            "uuid": job_uuid,
            "render_type": render_type,  # important
            "nsfw": nsfw,
            "agent_id": agent_id,
            "text_prompt": text_prompt,
            "steps": steps,
            "shape": shape,
            "model": model,
            "clip_guidance_scale": clip_guidance_scale,
            "diffusion_model": "512x512_diffusion_uncond_finetune_008100",
            "clamp_max": 0.05,
            "cut_ic_pow": cut_ic_pow,
            "cutn_batches": cutn_batches,
            "sat_scale": sat_scale,
            "set_seed": -1,
            "cut_schedule": cut_schedule,
            "author": author_id,
            "status": "processing",
            "timestamp": datetime.utcnow(),
            "last_preview": datetime.utcnow(),
        }
        queueCollection = client.database.get_collection("queue")
        queueCollection.insert_one(record)
        e = {"type": "progress", "agent": agent_id, "job_uuid": job_uuid, "percent": 0, "gpustats": None}
        event(e)

    dream_job = {"message ": f"You are dreaming.  (Job '{job_uuid}')", "uuid": job_uuid, "details": json.loads(dumps(record)), "success": True}
    return dream_job
