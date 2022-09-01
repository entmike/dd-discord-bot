import traceback
import random
from docarray import Document
from docarray import DocumentArray
from types import SimpleNamespace
import http.client
import urllib.parse
from email.policy import default
import re
from io import BytesIO, StringIO
from operator import truediv
from turtle import color, width
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
from json import loads
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

load_dotenv()

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "log", "lz4"}
MAX_DREAM_OCCURENCE = os.getenv("MAX_DREAM_OCCURENCE")

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_STALL_TIMEOUT = 120
BOT_SALT = os.getenv("BOT_SALT")
BOT_USE_S3 = os.getenv("BOT_USE_S3")
BOT_S3_BUCKET = os.getenv("BOT_S3_BUCKET")
BOT_S3_WEB = os.getenv("BOT_S3_WEB")
BOT_AWS_SERVER_PUBLIC_KEY = os.getenv("BOT_AWS_SERVER_PUBLIC_KEY")
BOT_AWS_SERVER_SECRET_KEY = os.getenv("BOT_AWS_SERVER_SECRET_KEY")
BOT_WEBSITE = os.getenv("BOT_WEBSITE")

ALGOLIA_APP_ID = os.getenv("ALGOLIA_APP_ID")
ALGOLIA_API_KEY = os.getenv("ALGOLIA_API_KEY")
ALGOLIA_INDEX_NAME = os.getenv("ALGOLIA_INDEX_NAME")

if BOT_USE_S3:
    session = boto3.Session(aws_access_key_id=BOT_AWS_SERVER_PUBLIC_KEY, aws_secret_access_key=BOT_AWS_SERVER_SECRET_KEY)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
CORS(app)

sys.path.append(".")
from db import get_database
from auth_utils import *
# from api_disco import *

def pulse(agent_id):
    with get_database() as client:
        agentCollection = client.database.get_collection("agents")
        agentCollection.update_one({"agent_id": agent_id}, {"$set": {"last_seen": datetime.utcnow()}})

def serve_pil_image(pil_img):
    img_io = BytesIO()
    pil_img.save(img_io, "JPEG", quality=70)
    img_io.seek(0)
    return send_file(img_io, mimetype="image/jpeg")


def s3_jpg(job_uuid, algo="disco"):
    try:
        if algo == "disco":
            try:
                url = f"{BOT_S3_WEB}{job_uuid}0_0.png"
                img = Image.open(urlopen(url))
            except:
                url = f"{BOT_S3_WEB}{job_uuid}.png"
                img = Image.open(urlopen(url))
        if algo == "stable":
            try:
                url = f"{BOT_S3_WEB}{job_uuid}.png"
                img = Image.open(urlopen(url))
            except:
                url = f"{BOT_S3_WEB}{job_uuid}.png"
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

def s3_thumbnail(job_uuid, size, algo="disco"):
    try:
        if algo == "disco":
            try:
                url = f"{BOT_S3_WEB}{job_uuid}0_0.png"
                img = Image.open(urlopen(url))
            except:
                url = f"{BOT_S3_WEB}{job_uuid}.png"
                img = Image.open(urlopen(url))
        if algo == "stable":
            try:
                url = f"{BOT_S3_WEB}{job_uuid}.png"
                img = Image.open(urlopen(url))
            except:
                pass

        img.thumbnail((int(size), int(size)), Image.LANCZOS)
        thumbfile = f"thumb_{size}_{job_uuid}.jpg"
        img.save(thumbfile, "JPEG")
        upload_file_s3(thumbfile, BOT_S3_BUCKET, f"thumbs/{size}/{job_uuid}.jpg", {"ContentType": "image/jpeg"})
        os.remove(thumbfile)
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        return f"Could not locate {url}.  This might be because the render has not completed yet.  Or because the job failed.  Or check your job uuid.  Or a gremlin ate the image.  Probably the gremlin.\n{tb}"

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

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

    try:
        response = s3_client.upload_file(file_name, bucket, object_name, extra_args)
    except Exception as e:
        logger.error(e)
        return False
    return True


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
            agentCollection.insert_one({"agent_id": agent_id, "last_seen": datetime.utcnow()})
            status = f"✅ Registered!  Your API token is '{token}'.  Save this, you won't see it again."
            log(f"A new agent has joined! 😍 Thank you, {agent_id}!", title="🆕 New Agent")
            success = True
        else:
            status = f"😓 Sorry, someone already registered an agent by that name.  Try another one!"
            success = False
    return jsonify({"message": status, "success": success})

def log(message, title="Message"):
    with get_database() as client:
        logTable = client.database.get_collection("logs")
        logTable.insert_one({"timestamp": datetime.utcnow(), "message": message, "title": title, "ack": False, "uuid": str(uuid.uuid4())})


@app.route("/pin/<uuid>", methods=["POST","DELETE"])
@requires_auth
def pin(uuid):
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    if request.method == "DELETE":
        with get_database() as client:
            client.database.pins.delete_many({"user_id": discord_id, "uuid" : uuid})
            return dumps({"success" : True, "message": f"📌 Unpinned {uuid} for {discord_id}"})

    if request.method == "POST":
        with get_database() as client:
            client.database.pins.update_one({
                    "user_id": discord_id,
                    "uuid" : uuid
                }, {
                "$set": {
                    "pinned_on": datetime.utcnow(),
                    "uuid": uuid
                }
            }, upsert=True)
        
        return dumps({"success" : True, "message": "Pinned"})

@app.route("/hide/<uuid>", methods=["POST","DELETE"])
@requires_auth
def hide(uuid):
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    if request.method == "DELETE":
        with get_database() as client:
            client.database.pieces.update_many({"author": discord_id, "uuid" : uuid},{"$set":{"hide" : False}})
            return dumps({"success" : True, "message": f"👀 Unhid {uuid} for {discord_id}"})

    if request.method == "POST":
        with get_database() as client:
            client.database.pieces.update_many({"author": discord_id, "uuid" : uuid},{"$set":{"hide" : True}})
            return dumps({"success" : True, "message": f"👀 Hid {uuid} for {discord_id}"})

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
                    "followed_on": datetime.utcnow(),
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

@app.route("/v2/recent/<type>/<amount>", methods=["GET"], defaults={"page": 1})
@app.route("/v2/recent/<type>/<amount>/<page>")
def v2_recent_images2(type, amount, page):
    q = {
        "status": {
            "$in":["archived","complete"]
        },
        "nsfw": {"$nin": [True]},
        "render_type": {"$ne": "sketch"}}
    
    if type == "disco":
        q["algo"] = {"$ne" : "stable"}
    
    if type == "stable":
        q["algo"] = "stable"
    
    if type == "general":
        q["diffusion_model"] = {"$in" : ["512x512_diffusion_uncond_finetune_008100","256x256_diffusion_uncond"]}

    if type == "portraits":
        q["diffusion_model"] = {"$in" : [
            "portrait_generator_v001_ema_0.9999_1MM",
            "portrait_generator_v1.5_ema_0.9999_165000",
            "portrait_generator_v003",
            "portrait_generator_v004",
            "512x512_diffusion_uncond_entmike_ffhq_025000",
            "512x512_diffusion_uncond_entmike_ffhq_145000",
            "512x512_diffusion_uncond_entmike_ffhq_260000"
            ]}

    if type == "isometric":
        q["diffusion_model"] = {"$in" : ["IsometricDiffusionRevrart512px"]}

    if type == "pixel-art":
        q["diffusion_model"] = {"$in" : ["pixel_art_diffusion_hard_256","pixel_art_diffusion_soft_256","pixelartdiffusion4k"]}

    if type == "paint-pour":
        q["diffusion_model"] = {"$in" : ["PaintPourDiffusion_v1.0","PaintPourDiffusion_v1.1","PaintPourDiffusion_v1.2","PaintPourDiffusion_v1.3"]}
    
    with get_database() as client:
        r = client.database.queue.aggregate(
            [
                {"$project": { "_id": 0 } },
                {"$unionWith": { "coll": "stable_jobs", "pipeline": [ { "$project": { "_id": 0 } } ]} },
                {"$match": q},
                {"$addFields": {"str_timestamp": {"$toString": "$timestamp"}}},
                {"$addFields": {"dt_timestamp": {"$dateFromString": {"dateString": "$str_timestamp"}}}},
                {"$sort": {"dt_timestamp": -1}},
                {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)},
                {"$unwind": {
                    "path": "$userdets",
                    "preserveNullAndEmptyArrays" : True
                }},
                {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
            ]
        )
        return dumps(r)



@app.route("/recent/<amount>", methods=["GET"], defaults={"page": 1})
@app.route("/recent/<amount>/<page>")
def recent_images2(amount, page):
    with get_database() as client:
        r = client.database.get_collection("queue").aggregate(
            [
                {"$match": {"status": {"$in":["archived","complete"]}, "nsfw": {"$nin": [True]}, "render_type": {"$ne": "sketch"}}},
                {"$addFields": {"str_timestamp": {"$toString": "$timestamp"}}},
                {"$addFields": {"dt_timestamp": {"$dateFromString": {"dateString": "$str_timestamp"}}}},
                {"$sort": {"dt_timestamp": -1}},
                {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)},
                {"$unwind": {
                    "path": "$userdets",
                    "preserveNullAndEmptyArrays" : True
                }},
                {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
            ]
        )
        return dumps(r)


@app.route("/random/<type>/<amount>", methods=["GET"])
@supports_auth
def v3_random(type, amount):
    user_info = _request_ctx_stack.top.user_info
    if user_info:
        user_id = int(user_info["user_id"].split("|")[2])
    else:
        user_id = None

    q = {
        "nsfw": {"$nin": [True]},
        "hide": {"$nin": [True]},
        "origin": "web",
        "thumbnails" : {"$exists" : True}
    }
    if type == "disco":
        q["algo"] = {"$ne" : "stable"}
    
    if type == "stable":
        q["algo"] = "stable"
        q["origin"] = "web"

    if type == "dream":
        q["algo"] = "stable"
        q["origin"] = "dream"


    with get_database() as client:
        operations = [
            {"$match": q},
            {"$sample": {"size": int(amount)}},
            {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
            {"$unwind": {
                "path": "$userdets",
                "preserveNullAndEmptyArrays" : True
            }},
            {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}}
        ]
        if user_id:
            operations.append({
            "$lookup" : {
                "from": "pins",
                "let": {
                    "user": user_id,
                    "uuid" : "$uuid"
                },
                "pipeline": [{
                    "$match": {
                        "$and": [
                            {"$expr": {"$eq": ['$user_id', '$$user'] }},
                            {"$expr": {"$eq": ['$uuid', '$$uuid'] }},
                        ]
                    }
                }],
                "as": "pinned"
            }})
            operations.append({
                "$unwind" : {
                    "path": "$pinned",
                    "includeArrayIndex": 'string',
                    "preserveNullAndEmptyArrays": True
                }
            })
        r = list(client.database.pieces.aggregate(operations))
        # Strip private params out
        for piece in r:
            try:
                if piece["private"] and piece["author"] != user_id:
                    del piece["params"]
            except:
                pass


        return dumps(r)

@app.route("/v2/userfeed/<user_id>/<amount>", methods=["GET"], defaults={"page": 1})
@app.route("/v2/userfeed/<user_id>/<amount>/<page>")
def v2_userfeed(user_id, amount, page):
    args = request.args   
    q = {
        "status": {"$in":["archived","complete","uploaded"]},
        "author_id": int(user_id),
        "nsfw": {"$nin": [True]},
        "hide": {"$nin": [True]},
    }
    
    if(args.get("hide")=="include"):
        del q["hide"]

    if(args.get("nsfw")=="include"):
        del q["nsfw"]

    if(args.get("nsfw")=="only"):
        q["nsfw"] = True

    with get_database() as client:
        r = client.database.queue.aggregate(
            [
                {"$project": { "_id": 0 } },
                {"$unionWith": { "coll": "stable_jobs", "pipeline": [ { "$project": { "_id": 0 } } ]} },
                {
                    "$addFields": {"author_id": {"$toLong": "$author"}},
                },
                {"$addFields": {"str_timestamp": {"$toString": "$timestamp"}}},
                {"$addFields": {"dt_timestamp": {"$dateFromString": {"dateString": "$str_timestamp"}}}},
                {"$match": q},
                {"$sort": {"dt_timestamp": -1}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)},
                {"$lookup": {"from": "users", "localField": "author_id", "foreignField": "user_id", "as": "userdets"}},
                {"$unwind": {
                    "path": "$userdets",
                    "preserveNullAndEmptyArrays" : True
                }},
                {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
            ]
        )
        return dumps(r)

@app.route("/getsince/<seconds>", methods=["GET"])
def getsince(seconds):
    since = datetime.utcnow() - timedelta(seconds=int(seconds))
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
        since = datetime.utcnow() - timedelta(minutes=BOT_STALL_TIMEOUT)
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
        queue = client.database.stable_jobs.aggregate(
            [
                {"$match": q},
                {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
                {"$unwind": {
                    "path": "$userdets",
                    "preserveNullAndEmptyArrays" : True
                }},
                {"$unwind": "$uuid"},
                {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
                {"$addFields": {"processingTime": {"$subtract": [datetime.utcnow(),"$last_preview"]}}}, # milliseconds
            ]
        )
        return dumps(queue)


@app.route("/queue/", methods=["GET"], defaults={"status": "all"})
@app.route("/queue/<status>/")
def queue(status):
    logger.info(f"Queue request for status {status}...")
    if status == "stalled":
        since = datetime.utcnow() - timedelta(minutes=BOT_STALL_TIMEOUT)
        q = {"status": "processing", "$or": [{"last_preview": {"$lt": since}}, {"last_preview": {"$exists": False}, "timestamp": {"$lt": since}}]}
    else:
        q = {"status": {"$nin": ["archived", "completed", "rejected"]}}
    # if who == "me":
    #     q["author"] = int(author)
    if status != "all" and status != "stalled":
        q["status"] = status
    # if status == "all" and who=="me":
    #     del q["status"]
    with get_database() as client:
        n = datetime.utcnow()
        query = {"$query": q, "$orderby": {"timestamp": -1}}
        queue = client.database.queue.aggregate([
            {"$match": q},
            # {"$limit": 10}
        ])
        
        e = datetime.utcnow()
        t = e - n
        # logger.info(f"{t} seconds elapsed")
        return dumps(queue)

@app.route("/stable_jobs/", methods=["GET"], defaults={"status": "all"})
@app.route("/stable_jobs/<status>/")
def stable_jobs(status):
    # logger.info(f"Queue request for status {status}...")
    if status == "stalled":
        since = datetime.utcnow() - timedelta(minutes=BOT_STALL_TIMEOUT)
        q = {"status": "processing", "$or": [{"last_preview": {"$lt": since}}, {"last_preview": {"$exists": False}, "timestamp": {"$lt": since}}]}
    else:
        q = {"status": {"$nin": ["archived", "completed", "rejected"]}}
    # if who == "me":
    #     q["author"] = int(author)
    if status != "all" and status != "stalled":
        q["status"] = status
    # if status == "all" and who=="me":
    #     del q["status"]
    with get_database() as client:
        n = datetime.utcnow()
        query = {"$query": q, "$orderby": {"timestamp": -1}}
        queue = client.database.stable_jobs.find(query)
        e = datetime.utcnow()
        t = e - n
        # logger.info(f"{t} seconds elapsed")
        return dumps(queue)

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
        doc = {"subject": request.form.get("subject"), "channel": int(request.form.get("channel")), "message": int(request.form.get("message")), "timestamp": datetime.utcnow()}
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
        post = queueCollection.update_many({"render_type": "nightmare"}, {"$set": {"nsfw": True}})
        return "ok"


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
        user = userCollection.find_one({ "user_id_str" : user_id})
        if user:
            return dumps(user)
        else:
            return dumps({
                "user_id_str" : str(user_id),
                "user_name" : "Unknown User"
            })

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

@app.route("/stable/job/<job_uuid>", methods=["GET"])
def stable_job(job_uuid):
    if request.method == "GET":
        logger.info(f"Accessing Stable Diffusion Job {job_uuid}...")
        with get_database() as client:
            stable_jobs = client.database.stable_jobs
            jobs = stable_jobs.aggregate(
                [
                    {"$match": {"uuid": job_uuid}},
                    {"$addFields": {"author_bigint": {"$toLong": "$author"}}},
                    {"$addFields": {"str_author": {"$toString": "$author"}}},
                    {"$lookup": {"from": "vw_users", "localField": "author_bigint", "foreignField": "user_id", "as": "userdets"}},
                    {"$unwind": {
                        "path": "$userdets",
                        "preserveNullAndEmptyArrays" : True
                    }},
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
            views += 1
            stable_jobs.update_one({"uuid": job_uuid}, {"$set": {"views": views}}, upsert=True)
            jobs[0]["views"] = views
            return dumps(jobs[0])

@app.route("/v2/meta/<job_uuid>", methods=["GET"], defaults={"mode" : "meta"})
@app.route("/v2/job/<job_uuid>", methods=["GET"], defaults={"mode" : "view"})
def v2_job(job_uuid, mode):
    if request.method == "GET":
        logger.info(f"Accessing {job_uuid}...")
        with get_database() as client:
            queueCollection = client.database.sanitized_jobs
            jobs = queueCollection.aggregate(
                [
                    {"$project": { "_id": 0 } },
                    {"$unionWith": { "coll": "stable_jobs", "pipeline": [ { "$project": { "_id": 0 } } ]} },
                    {"$match": {"uuid": job_uuid}},
                    {"$addFields": {"author_bigint": {"$toLong": "$author"}}},
                    {"$addFields": {"str_author": {"$toString": "$author"}}},
                    {"$lookup": {"from": "vw_users", "localField": "author_bigint", "foreignField": "user_id", "as": "userdets"}},
                    {"$unwind": {
                        "path": "$userdets",
                        "preserveNullAndEmptyArrays" : True
                    }},
                    {"$unwind": "$uuid"},
                    {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
                ]
            )
            jobs = list(jobs)
            if len(jobs) == 0:
                return dumps(None)
            
            if mode == "view":
                try:
                    views = jobs[0]["views"]
                except:
                    views = 0
                try:
                    algo = jobs[0]["algo"]
                except:
                    algo = "disco"

                # logger.info(jobs[0])
                # views = job[0].get("views")
                # if not views:
                #     views = 0
                if algo == "disco":
                    views += 1
                    client.database.queue.update_one({"uuid": job_uuid}, {"$set": {"views": views}}, upsert=True)
                    jobs[0]["views"] = views
                
                if algo == "stable":
                    views += 1
                    client.database.stable_jobs.update_one({"uuid": job_uuid}, {"$set": {"views": views}}, upsert=True)
                    jobs[0]["views"] = views

            return dumps(jobs[0])

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
                    {"$addFields": {"str_author": {"$toString": "$author"}}},
                    {"$lookup": {"from": "vw_users", "localField": "author_bigint", "foreignField": "user_id", "as": "userdets"}},
                    {"$unwind": {
                        "path": "$userdets",
                        "preserveNullAndEmptyArrays" : True
                    }},
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
            # logger.info(jobs[0])
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
        since = datetime.utcnow() - timedelta(minutes=60)
        agents = client.database.agents.find({"last_seen": {"$gt": since}}).sort("last_seen", -1)
        return dumps(agents)

@app.route("/agent/<agent_id>")
def agentstats(agent_id):
    with get_database() as client:
        agent = client.database.get_collection("agents").find_one({"agent_id": agent_id})
        return dumps(agent)

@app.route("/landingstats")
def landingstats():
    with get_database() as client:
        since = datetime.utcnow() - timedelta(minutes=60)
        userCount = client.database.users.count_documents({})
        completedCount = client.database.unified_jobs.count_documents({"status": "archived"})
        agentCount = client.database.agents.count_documents({"last_seen": {"$gt": since}})
        return dumps(
            {
                "completedCount": completedCount,
                "userCount": userCount,
                "agentCount": agentCount,
            }
        )


@app.route("/queuestats")
def queuestats():
    n = datetime.utcnow()
    with get_database() as client:
        queueCollection = client.database.unified_jobs
        queuedCount = queueCollection.count_documents({"status": "queued"})
        processingCount = queueCollection.count_documents({"status": "processing"})
        renderedCount = queueCollection.count_documents({"status": "archived"})
        completedCount = queueCollection.count_documents({"status": "complete"})
        rejectedCount = queueCollection.count_documents({"status": "rejected"})
        e = datetime.utcnow()
        t = e - n
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

@app.route("/reject/<agent_id>/<job_uuid>", methods=["POST"])
def reject(agent_id, job_uuid):
    pulse(agent_id=agent_id)
    logger.error(f"❌ Rejecting {job_uuid} - Details in traceback in DB.")
    tb = request.form.get("traceback")
    log = request.form.get("log")
    # logger.info(log)
    # logger.info(tb)
    if request.method == "POST":
        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            results = queueCollection.update_one({"agent_id": agent_id, "uuid": job_uuid}, {"$set": {"status": "failed", "filename": None, "log": log, "traceback": tb}})
            count = results.modified_count
            # if it's a dream delete it.
            results = queueCollection.delete_many({"agent_id": agent_id, "uuid": job_uuid, "origin" : "dream"})
        if count == 0:
            return f"cannot find that job."
        else:
            return f"job rejected, {agent_id}."

@app.route("/stable/reject/<agent_id>/<job_uuid>", methods=["POST"])
def stable_reject(agent_id, job_uuid):
    pulse(agent_id=agent_id)
    logger.error(f"❌ Rejecting {job_uuid} - Details in traceback in DB.")
    tb = request.form.get("traceback")
    log = request.form.get("log")
    # logger.info(log)
    # logger.info(tb)
    if request.method == "POST":
        with get_database() as client:
            results = client.database.stable_jobs.update_one({"agent_id": agent_id, "uuid": job_uuid}, {"$set": {"status": "failed", "filename": None, "log": log, "traceback": tb}})
            count = results.modified_count
            # if it's a dream delete it.
            results = client.database.stable_jobs.delete_many({"agent_id": agent_id, "uuid": job_uuid, "render_type" : "dream"})
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
        # event(e)
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
            # event(e)
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
            process_upload(job_uuid, filepath, filename)
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

@app.route("/web/profile", methods=["POST"])
@requires_auth
def web_profile():
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    profile = request.json.get("profile")
    with get_database() as client:
        client.database.users.update_one({"user_id": discord_id}, {"$set" : {"social" : profile["social"]}})
    return dumps({"success" : True})

@app.route("/web/agentjobs/<agent>", methods=["GET"], defaults={"page": 1})
@app.route("/web/agentjobs/<agent>/<page>", methods=["GET"])
def web_agentjobs(agent, page):
    with get_database() as client:
        q = {"agent_id" : agent}
        amount = 25
        jobs = client.database.vw_queue.aggregate(
            [
                {"$match": q},
                {"$sort": {"dt_timestamp": -1}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)}
            ])
        return dumps(jobs)

@app.route("/web/myjobs", methods=["GET"], defaults={"status": all, "page": 1})
@app.route("/web/myjobs/<status>", methods=["GET"], defaults={"status": all, "page": 1})
@app.route("/web/myjobs/<status>/<page>", methods=["GET"])
@requires_auth
def web_myjobs(status, page):
    current_user = _request_ctx_stack.top.current_user
    user_info = _request_ctx_stack.top.user_info
    logger.info(user_info)
    discord_id = int(current_user["sub"].split("|")[2])
    # status = "all"
    with get_database() as client:
        q = {"author" : {"$in": [discord_id, str(discord_id)]}}
        if status == "failed":
            q["status"]={"$in":["rejected","failed"]}
        if status == "queued":
            q["status"]={"$in":["queued"]}
            
        amount = 25
        with get_database() as client:
            jobs = client.database.stable_jobs.aggregate(
            [
                {"$match": q},
                {"$sort": {"timestamp": -1}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)}
            ])
        return dumps(jobs)

@app.route("/upscale/<uuid>", methods=["GET","POST"])
@requires_auth
def upscale(uuid):
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    augmentation = request.json.get("augmentation")
    with get_database() as client:
        j = client.database.pieces.find_one({"uuid" : uuid})
        if not j:
            return dumps({
                "success" : False,
                "message" : f"Cannot upscale piece: {j['uuid']}."
            })
        else:
            augs = j.get("augs")
            if not augs:
                augs = []
            try:
                params = {
                    "uuid" : uuid,
                    "model_name" : augmentation["model_name"],
                    "tile" : 0,
                    "tile_pad" : 10,
                    "pre_pad" : 0,
                    "face_enhance" : augmentation["face_enhance"],
                    "outscale" : augmentation["outscale"],
                    "fp32" : True
                }
                ns_params = SimpleNamespace(**params)
                p = json.dumps(ns_params.__dict__, indent = 4)
                param_hash = str(hashlib.sha256(p.encode('utf-8')).hexdigest())
                found = False
                for aug in augs:
                    if aug["augid"] == param_hash:
                        found = True
                if not found:
                    augs.append({
                        "augid" : param_hash,
                        "status" : "requested",
                        "params" : params
                    })
                    client.database.pieces.update_one({"uuid" : uuid, "author" : discord_id},{"$set":{
                        "augs" : augs
                    }})
                    return dumps({
                        "success" : True,
                        "message" : f"Upscale request for {j['uuid']} submitted."
                    })
                else:
                    return dumps({
                        "success" : False,
                        "message" : f"Augmentation already exists."
                    })
            except:
                logger.error("Error requesting upscale")
                return dumps({
                    "success" : False,
                    "message" : f"Error on upscale request for {j['uuid']}."
                })

@app.route("/reportnsfw", methods=["POST"])
@requires_auth
def reportnsfw():
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    job = request.json.get("job")
    nsfw_count = 0
    with get_database() as client:
        j = client.database.pieces.find_one({"uuid" : job["uuid"]})
        if not j:
            return dumps({
                "success" : False,
                "message" : f"Cannot report piece: {j['uuid']}."
            })
        else:
            try:
                n = client.database.nsfw_reports.find_one({"uuid" : job["uuid"], "reported_by" : discord_id})
            except:
                n = None
            
            if not n:
                client.database.nsfw_reports.insert_one({
                    "uuid" : job["uuid"],
                    "timestamp" : datetime.utcnow(),
                    "reported_by" : discord_id,
                    "new" : True
                })
                return dumps({
                    "success" : True,
                    "message" : f"Piece {j['uuid']} reported as NSFW.  Thank you!"
                })
            else:
                return dumps({
                "success" : True,
                "message" : f"You already reported this."
            })
            
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

@app.route("/stable/updatejob", methods=["POST"])
def stable_updatejob():
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    uuid = request.form.get("uuid")
    # logger.info(f"Updating job '{uuid}'")
    vals = request.form
    newvals = {}
    for val in vals:
        newvals[val] = vals[val]

    with get_database() as client:
        result = client.database.stable_jobs.update_one({"uuid": uuid}, {"$set": newvals})
        logger.info(f"Updated {uuid} ({result.matched_count})")
        return dumps({"matched_count": result.matched_count})

@app.route("/v3/landingstats")
def v3_landingstats():
    with get_database() as client:
        since = datetime.utcnow() - timedelta(minutes=60)
        userCount = client.database.users.count_documents({})
        completedCount = client.database.pieces.count_documents({})
        agentCount = client.database.agents.count_documents({"last_seen": {"$gt": since}})
        return dumps(
            {
                "completedCount": completedCount,
                "userCount": userCount,
                "agentCount": agentCount,
            }
        )

@app.route("/v3/bot/updatejob", methods=["POST"])
def v3_updatejob():
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    uuid = request.form.get("uuid")
    vals = request.form
    newvals = {}
    for val in vals:
        newvals[val] = vals[val]

    with get_database() as client:
        result = client.database.pieces.update_one({"uuid": uuid}, {"$set": newvals})
        logger.info(f"Updated {uuid} ({result.matched_count})")
        return dumps({"matched_count": result.matched_count})

@app.route("/v3/queuestats")
def v3_queuestats():
    n = datetime.utcnow()
    with get_database() as client:
        queueCollection = client.database.vw_all
        queuedCount = queueCollection.count_documents({"status": "queued"})
        processingCount = queueCollection.count_documents({"status": "processing"})
        renderedCount = queueCollection.count_documents({"status": "archived"})
        completedCount = queueCollection.count_documents({"status": "complete"})
        rejectedCount = queueCollection.count_documents({"status": "rejected"})
        e = datetime.utcnow()
        t = e - n
        return dumps(
            {"queuedCount": queuedCount, "processingCount": processingCount, "renderedCount": renderedCount, "rejectedCount": rejectedCount, "completedCount": completedCount}
        )

@app.route("/v3/myfavs/<amount>", methods=["GET"], defaults={"page": 1})
@app.route("/v3/myfavs/<amount>/<page>")
@supports_auth
def v3_myfavs(amount, page):
    user_info = _request_ctx_stack.top.user_info
    if user_info:
        user_id = int(user_info["user_id"].split("|")[2])
    else:
        user_id = None
    
    try:
        with get_database() as client:
            r = list(client.database.pins.aggregate([
                {"$match" : {"user_id" : user_id}},
                {"$sort": {"pinned_on": -1}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)},
                {"$lookup": {"from": "pieces", "localField": "uuid", "foreignField": "uuid", "as": "pieces"}},
                {"$unwind": {
                    "path": "$pieces",
                    "preserveNullAndEmptyArrays" : False
                }},
                {"$replaceRoot" : {
                "newRoot": "$pieces"
                }},
                {"$addFields": {
                    "pinned": True
                }},
                {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
                {"$unwind": {
                    "path": "$userdets",
                    "preserveNullAndEmptyArrays" : True
                }},
                {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
                ]))
            
            # Strip private params out
            for piece in r:
                try:
                    if piece["private"] and piece["author"] != user_id:
                        del piece["params"]
                except:
                    pass

            return dumps(r)
    except:
        tb = traceback.format_exc()
        logger.error(tb)
        return dumps({
            "success" : False,
            "message" : "Delivery failed!",
            "traceback" : tb
        })

@app.route("/v3/recent/<type>/<amount>", methods=["GET"], defaults={"page": 1})
@app.route("/v3/recent/<type>/<amount>/<page>")
@supports_auth
def v3_recent(type, amount, page):
    user_info = _request_ctx_stack.top.user_info
    if user_info:
        user_id = int(user_info["user_id"].split("|")[2])
    else:
        user_id = None
    q = {
        "nsfw": {"$nin": [True]},
        "hide": {"$nin": [True]},
        "thumbnails" : {"$exists" : True},
        "origin": "web"
    }
    if type == "disco":
        q["algo"] = {"$ne" : "stable"}
    
    if type == "stable":
        q["algo"] = "stable"
        q["origin"] = "web"

    if type == "dream":
        q["algo"] = "stable"
        q["origin"] = "dream"

    if type == "general":
        q["algo"] = "disco"
        q["diffusion_model"] = {"$in" : ["512x512_diffusion_uncond_finetune_008100","256x256_diffusion_uncond"]}

    if type == "portraits":
        q["algo"] = "disco"
        q["diffusion_model"] = {"$in" : [
            "portrait_generator_v001_ema_0.9999_1MM",
            "portrait_generator_v1.5_ema_0.9999_165000",
            "portrait_generator_v003",
            "portrait_generator_v004",
            "512x512_diffusion_uncond_entmike_ffhq_025000",
            "512x512_diffusion_uncond_entmike_ffhq_145000",
            "512x512_diffusion_uncond_entmike_ffhq_260000"
            ]}

    if type == "isometric":
        q["algo"] = "disco"
        q["diffusion_model"] = {"$in" : ["IsometricDiffusionRevrart512px"]}

    if type == "pixel-art":
        q["algo"] = "disco"
        q["diffusion_model"] = {"$in" : ["pixel_art_diffusion_hard_256","pixel_art_diffusion_soft_256","pixelartdiffusion4k"]}

    if type == "paint-pour":
        q["diffusion_model"] = {"$in" : ["PaintPourDiffusion_v1.0","PaintPourDiffusion_v1.1","PaintPourDiffusion_v1.2","PaintPourDiffusion_v1.3"]}
    
    operations = [
        {"$match": q},
        {"$addFields": {"str_timestamp": {"$toString": "$timestamp"}}},
        {"$addFields": {"dt_timestamp": {"$dateFromString": {"dateString": "$str_timestamp"}}}},
        {"$sort": {"dt_timestamp": -1}},
        {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
        {"$skip": (int(page) - 1) * int(amount)},
        {"$limit": int(amount)},
        {"$unwind": {
            "path": "$userdets",
            "preserveNullAndEmptyArrays" : True
        }},
        {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
    ]
    if user_id:
        operations.append({
        "$lookup" : {
            "from": "pins",
            "let": {
                "user": user_id,
                "uuid" : "$uuid"
            },
            "pipeline": [{
                "$match": {
                    "$and": [
                        {"$expr": {"$eq": ['$user_id', '$$user'] }},
                        {"$expr": {"$eq": ['$uuid', '$$uuid'] }},
                    ]
                }
            }],
            "as": "pinned"
        }})
        operations.append({
            "$unwind" : {
                "path": "$pinned",
                "includeArrayIndex": 'string',
                "preserveNullAndEmptyArrays": True
            }
        })

    with get_database() as client:
        r = list(client.database.pieces.aggregate(operations))
        
        # Strip private params out
        for piece in r:
            try:
                if piece["private"] and piece["author"] != user_id:
                    del piece["params"]
            except:
                pass
        
        return dumps(r)
@app.route("/v3/cancel", methods=["POST"])
@requires_auth
def v3_cancel():
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    job_uuid = request.json.get("uuid")
    with get_database() as client:
        job = client.database.queue.find_one({"uuid": job_uuid, "author" : discord_id})
        logger.info(job)
        if not job:
            logger.info(f"❌ Cancel Error: {job_uuid} not found for {discord_id}")
            return dumps({
                "message" : "Job could not be marked for cancel.",
                "success" : False
            })


    with get_database() as client:
        client.database.queue.delete_one({"uuid": job_uuid, "author" : discord_id})       

    return dumps({
        "message" : "Job cancelled.",
        "success" : True
    })

@app.route("/v3/reject/<agent_id>/<job_uuid>", methods=["POST"])
def v3_reject(agent_id, job_uuid):
    pulse(agent_id=agent_id)
    logger.error(f"❌ Rejecting {job_uuid} - Details in traceback in DB.")
    tb = request.form.get("traceback")
    log = request.form.get("log")
    # logger.info(log)
    # logger.info(tb)
    if request.method == "POST":
        with get_database() as client:
            queueCollection = client.database.queue
            results = queueCollection.update_one({"agent_id": agent_id, "uuid": job_uuid}, {"$set": {"status": "failed", "filename": None, "log": log, "traceback": tb}})
            count = results.modified_count
            # if it's a dream delete it.
            results = queueCollection.delete_many({"agent_id": agent_id, "uuid": job_uuid, "render_type" : "dream"})
        if count == 0:
            return f"cannot find that job."
        else:
            return f"job rejected, {agent_id}."

@app.route("/fix")
def fix():
    with get_database() as client:
        broken = client.database.pieces.find({"params.prompt" : {"$exists":False}})
        for broke in broken:
            width_height = broke["width_height"]
            prompt = broke["prompt"]
            seed = broke["seed"]
            steps = broke["steps"]
            scale = broke["scale"]
            eta = broke["eta"]
            prompt_hash = str(hashlib.sha256(prompt.encode('utf-8')).hexdigest())
            weights_hash = "54632c6e8a36eecae65e36cb0595fab314e1a1545a65209f24fde221a8d4b2ca"   #1.3_full
            params = {
                "weights" : weights_hash,     #1.3
                "n_samples" : 1,
                "prompt": prompt,
                "seed": seed,
                "steps": steps,
                "scale": scale,
                "eta": eta,
                "width_height": width_height
            }

            ns_params = SimpleNamespace(**params)
            p = json.dumps(ns_params.__dict__, indent = 4)
            param_hash = str(hashlib.sha256(p.encode('utf-8')).hexdigest())
            if width_height:
                logger.info(broke["uuid"])
                client.database.pieces.update_one({ "uuid" : broke["uuid"] }, {"$set": {
                    "params" : params,
                    "prompt_hash" : prompt_hash
                }})



@app.route("/v3/retry", methods=["POST"])
@requires_auth
def v3_retry():
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    job_uuid = request.json.get("uuid")
    with get_database() as client:
        job = client.database.queue.find_one({"uuid": job_uuid, "author" : discord_id})
        logger.info(job)
        if not job:
            logger.info(f"❌ Retry Error: {job_uuid} not found for {discord_id}")
            return dumps({
                "message" : "Job could not be marked for retry.",
                "success" : False
            })

        client.database.queue.update_one({"uuid": job_uuid, "author" : discord_id}, {
            "$set": {
                "user_id": discord_id,
                "status": "queued",
                "avoid_last_agent": True
            }
        }, upsert=True)
    
    return dumps({
        "message" : "Job marked for retry.",
        "success" : True
    })

@app.route("/v3/myjobs", methods=["GET"], defaults={"status": all, "page": 1})
@app.route("/v3/myjobs/<status>", methods=["GET"], defaults={"status": all, "page": 1})
@app.route("/v3/myjobs/<status>/<page>", methods=["GET"])
@requires_auth
def v3_myjobs(status, page):
    current_user = _request_ctx_stack.top.current_user
    user_info = _request_ctx_stack.top.user_info
    logger.info(user_info)
    discord_id = int(current_user["sub"].split("|")[2])
    # status = "all"
    with get_database() as client:
        q = {"author" : {"$in": [discord_id, str(discord_id)]}}
        if status == "failed":
            q["status"]={"$in":["rejected","failed"]}
        if status == "queued":
            q["status"]={"$in":["queued"]}
            
        amount = 25
        with get_database() as client:
            jobs = client.database.vw_all.aggregate(
            [
                {"$match": q},
                {"$sort": {"timestamp": -1}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)}
            ])
        return dumps(jobs)


@app.route("/v3/userfeed/<gallery_id>/<amount>", methods=["GET"], defaults={"page": 1})
@app.route("/v3/userfeed/<gallery_id>/<amount>/<page>")
@supports_auth
def v3_userfeed(gallery_id, amount, page):
    user_info = _request_ctx_stack.top.user_info
    if user_info:
        user_id = int(user_info["user_id"].split("|")[2])
    else:
        user_id = None

    args = request.args   
    q = {
        "author_id": int(gallery_id),
        "nsfw": {"$nin": [True]},
        "hide": {"$nin": [True]},
    }
    
    if(args.get("hide")=="include"):
        del q["hide"]

    if(args.get("nsfw")=="include"):
        del q["nsfw"]

    if(args.get("nsfw")=="only"):
        q["nsfw"] = True

    with get_database() as client:
        operations = [
            {
                "$addFields": {"author_id": {"$toLong": "$author"}},
            },
            {"$addFields": {"str_timestamp": {"$toString": "$timestamp"}}},
            {"$addFields": {"dt_timestamp": {"$dateFromString": {"dateString": "$str_timestamp"}}}},
            {"$match": q},
            {"$sort": {"dt_timestamp": -1}},
            {"$skip": (int(page) - 1) * int(amount)},
            {"$limit": int(amount)},
            {"$lookup": {"from": "users", "localField": "author_id", "foreignField": "user_id", "as": "userdets"}},
            {"$unwind": {
                "path": "$userdets",
                "preserveNullAndEmptyArrays" : True
            }},
            {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
        ]
        if user_id:
            operations.append({
            "$lookup" : {
                "from": "pins",
                "let": {
                    "user": user_id,
                    "uuid" : "$uuid"
                },
                "pipeline": [{
                    "$match": {
                        "$and": [
                            {"$expr": {"$eq": ['$user_id', '$$user'] }},
                            {"$expr": {"$eq": ['$uuid', '$$uuid'] }},
                        ]
                    }
                }],
                "as": "pinned"
            }})
            operations.append({
                "$unwind" : {
                    "path": "$pinned",
                    "includeArrayIndex": 'string',
                    "preserveNullAndEmptyArrays": True
                }
            })
        
        r = list(client.database.pieces.aggregate(operations))

        # Strip private params out
        for piece in r:
            try:
                if piece["private"] and piece["author"] != user_id:
                    del piece["params"]
            except:
                pass
        
        return dumps(r)

@app.route("/v3/related/<uuid>/<amount>", methods=["GET"], defaults={"page": 1})
@app.route("/v3/related/<uuid>/<amount>/<page>")
@supports_auth
def v3_related(uuid, amount, page):
    user_info = _request_ctx_stack.top.user_info
    if user_info:
        user_id = int(user_info["user_id"].split("|")[2])
    else:
        user_id = None
    with get_database() as client:
        piece = client.database.pieces.find_one({"uuid" : uuid})
        if piece:
            prompt_hash = piece.get("prompt_hash")

    args = request.args   
    q = {
        "prompt_hash": prompt_hash,
        "uuid" : {"$ne" : uuid},
        "nsfw": {"$nin": [True]},
        "hide": {"$nin": [True]},
    }
    
    if(args.get("hide")=="include"):
        del q["hide"]

    if(args.get("nsfw")=="include"):
        del q["nsfw"]

    if(args.get("nsfw")=="only"):
        q["nsfw"] = True

    with get_database() as client:
        operations = [
            {"$match": q},
            {"$sample": {"size": int(amount)}},
            {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
            {"$unwind": {
                "path": "$userdets",
                "preserveNullAndEmptyArrays" : True
            }},
            {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
        ]
        if user_id:
            operations.append({
            "$lookup" : {
                "from": "pins",
                "let": {
                    "user": user_id,
                    "uuid" : "$uuid"
                },
                "pipeline": [{
                    "$match": {
                        "$and": [
                            {"$expr": {"$eq": ['$user_id', '$$user'] }},
                            {"$expr": {"$eq": ['$uuid', '$$uuid'] }},
                        ]
                    }
                }],
                "as": "pinned"
            }})
            operations.append({
                "$unwind" : {
                    "path": "$pinned",
                    "includeArrayIndex": 'string',
                    "preserveNullAndEmptyArrays": True
                }
            })
        
        r = list(client.database.pieces.aggregate(operations))

        # Strip private params out
        for piece in r:
            try:
                if piece["private"] and piece["author"] != user_id:
                    del piece["params"]
            except:
                pass

        return dumps(r)


@app.route("/v3/meta/<job_uuid>", methods=["GET"], defaults={"mode" : "meta"})
@app.route("/v3/job/<job_uuid>", methods=["GET"], defaults={"mode" : "view"})
@supports_auth
def v3_job(job_uuid, mode):
    auth = request.headers.get("Authorization", None)
    user_info = _request_ctx_stack.top.user_info
    if user_info:
        user_id = int(user_info["user_id"].split("|")[2])
    else:
        user_id = None

    if request.method == "GET":
        logger.info(f"Accessing {job_uuid}...")
        with get_database() as client:
            queueCollection = client.database.vw_all
            operations = [
                {"$match": {"uuid": job_uuid}},
                {"$addFields": {"author_bigint": {"$toLong": "$author"}}},
                {"$addFields": {"str_author": {"$toString": "$author"}}},
                {"$lookup": {"from": "vw_users", "localField": "author_bigint", "foreignField": "user_id", "as": "userdets"}},
                {"$unwind": {
                    "path": "$userdets",
                    "preserveNullAndEmptyArrays" : True
                }},
                {"$unwind": "$uuid"},
                {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
            ]
            if user_id:
                operations.append(
                    # "$lookup": {"from": "pins", "localField": "uuid", "foreignField": "uuid", "as": "pinned"}
                    { "$lookup": {
                    "as": "pinned",
                    "from" : "pins",
                    "let" : { "uuid" : "$uuid" },
                    "pipeline": [
                        {
                            "$match": {
                                "$and": [
                                    {"$expr": {"$eq": ['$user_id', user_id] }},
                                    {"$expr": {"$eq": ['$uuid', '$$uuid'] }},
                                ]} 
                        },
                    ]}
                })
                operations.append({"$unwind": {
                    "path": "$pinned",
                    "preserveNullAndEmptyArrays" : True
                }})
            jobs = queueCollection.aggregate(operations)
            jobs = list(jobs)
            if len(jobs) == 0:
                return dumps(None)
            
            job = jobs[0]

            if mode == "view":
                try:
                    views = job["views"]
                except:
                    views = 0
                
                views += 1
                collection = job["source"]
                client.database.get_collection(collection).update_one({"uuid": job_uuid}, {"$set": {
                    "views": views
                }}, upsert=True)
                job["views"] = views
            
            logger.info(job)
            # Strip private params out
            try:
                if job["private"] and job["author"] != user_id:
                    del job["params"]
            except:
                pass

            return dumps(job)



# @app.route("/v3/job/<job_uuid>", methods=["GET"])
# def v3_job(job_uuid):
#     if request.method == "GET":
#         logger.info(f"Accessing Job {job_uuid}...")
#         with get_database() as client:
#             jobs = client.database.vw_all.aggregate(
#                 [
#                     {"$match": {"uuid": job_uuid}},
#                     {"$addFields": {"author_bigint": {"$toLong": "$author"}}},
#                     {"$addFields": {"str_author": {"$toString": "$author"}}},
#                     {"$lookup": {"from": "vw_users", "localField": "author_bigint", "foreignField": "user_id", "as": "userdets"}},
#                     {"$unwind": {
#                         "path": "$userdets",
#                         "preserveNullAndEmptyArrays" : True
#                     }},
#                     {"$unwind": "$uuid"},
#                     {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
#                 ]
#             )
#             jobs = list(jobs)
#             if len(jobs) == 0:
#                 return dumps(None)
#             try:
#                 job = jobs[0]
#                 views = job["views"]
#             except:
#                 views = 0
#             views += 1
#             source = job["source"]
#             client.database.get_collection(source).update_one({"uuid": job_uuid}, {"$set": {"views": views}}, upsert=True)
#             job["views"] = views
            
#             if job["private"]:
#                 del job["params"]
            
#             return dumps(job)

def v3_queue(status):
    logger.info(f"📃 Queue request for status {status}...")
    if status == "stalled":
        since = datetime.utcnow() - timedelta(minutes=BOT_STALL_TIMEOUT)
        q = {"status": "processing", "timestamp": {"$lt": since}}
    else:
        q = {"status": {"$nin": ["archived", "rejected"]}}
    if status != "all" and status != "stalled":
        q["status"] = status
    with get_database() as client:
        query = {"$query": q, "$orderby": {"timestamp": -1}}
        queue = client.database.queue.aggregate(
            [
                {"$match": q},
                {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
                {"$unwind": {
                    "path": "$userdets",
                    "preserveNullAndEmptyArrays" : True
                }},
                {"$unwind": "$uuid"},
                {"$addFields": {"userdets.user_str": {"$toString": "$userdets.user_id"}}},
                {"$addFields": {"processingTime": {"$subtract": [datetime.utcnow(),"$last_preview"]}}}, # milliseconds
            ]
        )
        return list(queue)

@app.route("/v3/public_queue/", methods=["GET"], defaults={"status": "all"})
@app.route("/v3/public_queue/<status>/")
def v3_public_queue(status):
    queue = v3_queue(status)
    
    # Strip private params out
    for item in queue:
        if "private" in item:
            try:
                if item["private"]:
                    del item["params"]
            except:
                pass
        

    return dumps(queue)

@app.route("/v3/create/edit", methods=["POST"], defaults={"mode" : "edit"})
@app.route("/v3/create/update", methods=["POST"], defaults={"mode" : "update"})
@app.route("/v3/create/mutate", methods=["POST"], defaults={"mode" : "mutate"})
@requires_auth
def create(mode):
    user_info = _request_ctx_stack.top.user_info
    user_id = int(user_info["user_id"].split("|")[2])
    timestamp = datetime.utcnow()
    logger.info(f"📷 Incoming job request ({mode}) from {user_id} ({user_info['name']})...")
    job = request.json.get("job")
    
    # NEW/EDIT
    if mode == "mutate" or mode == "edit":
        jobparams = job["params"]
        
        if job["algo"] == "stable":
            weights_hash = "fe4efff1e174c627256e44ec2991ba279b3816e364b49f9be2abc0b3ff3f8556"
        else:
            weights_hash = "N/A"

        seed = int(jobparams["seed"])
        prompt = jobparams["prompt"]
        prompt_hash = str(hashlib.sha256(prompt.encode('utf-8')).hexdigest())

        try:
            batch_size = int(job["batch_size"])
        except:
            batch_size = 1
        if seed == -1:
            seed = random.randint(0, 2**32)
        results = []
        for i in range(batch_size):
            new_seed = seed+i
            logger.info(f"{i+1} of {batch_size} - Seed: {seed+i}")
            params = {
                "weights" : weights_hash,     #1.4
                "n_samples" : 1,
                "prompt": prompt,
                "seed": new_seed,
                "steps": jobparams["steps"],
                "scale": jobparams["scale"],
                "eta": jobparams["eta"],
                "width_height": jobparams["width_height"]
            }

            ns_params = SimpleNamespace(**params)
            p = json.dumps(ns_params.__dict__, indent = 4)
            param_hash = str(hashlib.sha256(p.encode('utf-8')).hexdigest())

            newrecord = {
                "weights" : weights_hash,
                "hide": False,
                "uuid": param_hash,
                "preferred_image" : param_hash,
                "algo" : "stable",
                "nsfw": job["nsfw"],
                "private": job["private"],
                "author": user_id,
                "status": "queued",
                "timestamp": timestamp,
                "origin": "web",
                "n_samples" : 1,
                "prompt_hash" : prompt_hash,
                # "gpu_preference": job["gpu_preference"],
                "width_height": job["width_height"],
                "params" : ns_params.__dict__
            }
            
            with get_database() as client:
                j = client.database.vw_all.find_one({"uuid" : param_hash})
                if j:
                    logger.info(f"⚠️ Hash {param_hash} already exists.")
                    results.append({
                        "success" : False,
                        "uuid" : param_hash,
                        "message" : f"Render {param_hash} already exists."
                    })
                else:
                    logger.info(f"Adding job {param_hash} to queue.")
                    if mode == "mutate":
                        client.database.queue.insert_one(newrecord)
                        results.append({
                            "success" : True,
                            "uuid" : param_hash,
                            "message" : f"✅ Render {param_hash} submitted successfully."
                        })
                    if mode == "edit":
                        old_hash = job["uuid"]
                        client.database.queue.update_one({"uuid":old_hash},{
                            "$set" : newrecord
                        })
                        results.append({
                            "success" : True,
                            "uuid" : param_hash,
                            "message" : f"✅ Render {param_hash} editted successfully."
                        })
        return dumps({"success" : True, "results" : results})
   
    # UPDATE
    if mode == "update":
        with get_database() as client:
            j = client.database.vw_all.find_one({"uuid" : job["uuid"], "author" : user_id})
            if not j:
                return dumps({
                    "success" : False,
                    "message" : f"You cannot update {j['uuid']}."
                })
            else:
                logger.info(f"Updating job {job['uuid']} by {str(user_id)}...")
                with get_database() as client:
                    try:
                        preferredImage = job["preferredImage"]
                    except:
                        preferredImage = job["uuid"]
                    updateParams = {
                        "private" : job["private"],
                        "nsfw" : job["nsfw"],
                        "hide" : job["hide"],
                        "preferredImage" : preferredImage
                    }
                    client.database.get_collection(j["source"]).update_one({"uuid": job["uuid"], "author" : user_id}, {"$set": updateParams})
                return dumps({
                    "success" : True,
                    "message" : f"{job['uuid']} successfully updated."
                })
    

    return dumps({"success" : False, "results" : "Unknown instruction"})


@app.route("/web/stable/update", methods=["POST"], defaults={"mode" : "update"})
@app.route("/web/stable/edit", methods=["POST"], defaults={"mode" : "edit"})
@app.route("/web/stable/mutate", methods=["POST"], defaults={"mode" : "mutate"})
@requires_auth
def web_stable(mode):
    import random

    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    algo = 'stable'

    timestamp = datetime.utcnow()
    logger.info(f"Incoming Stable Diffusion job request from {discord_id}...")
    job = request.json.get("job")
    
    # EDIT
    if mode == "edit":
        return dumps({
            "success" : False,
            "message" : "You cannot edit this job."
        })

    # UPDATE
    if mode == "update":
        with get_database() as client:
            j = client.database.stable_jobs.find_one({"uuid" : job["uuid"], "author" : discord_id})
            if not j:
                return dumps({
                    "success" : False,
                    "message" : f"You cannot update {j['uuid']}."
                })
            else:
                logger.info(f"Updating job {job['uuid']} by {str(discord_id)}...")
                with get_database() as client:
                    updateParams = {
                        "private" : job["private"],
                        "nsfw" : job["nsfw"],
                        "hide" : job["hide"]
                    }
                    client.database.stable_jobs.update_one({"uuid": job["uuid"], "author" : discord_id}, {"$set": updateParams})
                return dumps({
                    "success" : True,
                    "message" : f"{job['uuid']} successfully updated."
                })

    #CREATE  
    if mode == "mutate":
        seed = int(job["seed"])
        prompt = job["prompt"]
        prompt_hash = str(hashlib.sha256(prompt.encode('utf-8')).hexdigest())

        try:
            batch_size = int(job["batch_size"])
        except:
            batch_size = 1
        if seed == -1:
            seed = random.randint(0, 2**32)
        results = []
        for i in range(batch_size):
            new_seed = seed+i
            logger.info(f"{i} of {batch_size} - Seed: {seed+i}")
            params = {
                "weights" : "fe4efff1e174c627256e44ec2991ba279b3816e364b49f9be2abc0b3ff3f8556",     #1.4
                "n_samples" : 1,
                "prompt": prompt,
                "seed": new_seed,
                "steps": job["steps"],
                "scale": job["scale"],
                "eta": job["eta"]
            }

            ns_params = SimpleNamespace(**params)
            p = json.dumps(ns_params.__dict__, indent = 4)
            param_hash = str(hashlib.sha256(p.encode('utf-8')).hexdigest())

            newrecord = {
                "weights" : "fe4efff1e174c627256e44ec2991ba279b3816e364b49f9be2abc0b3ff3f8556",
                "hide": False,
                "uuid": param_hash,
                "algo" : algo,
                "nsfw": job["nsfw"],
                "private": job["private"],
                "author": discord_id,
                "status": "queued",
                "timestamp": timestamp,
                "origin": "web",
                "n_samples" : 1,
                "prompt": prompt,
                "prompt_hash" : prompt_hash,
                "seed": new_seed,
                "steps": job["steps"],
                "gpu_preference": job["gpu_preference"],
                "width_height": job["width_height"],
                "scale": job["scale"],
                "eta": job["eta"],
                "params" : ns_params.__dict__
            }
            
            with get_database() as client:
                j = client.database.stable_jobs.find_one({"uuid" : param_hash})
                if j:
                    results.append({
                        "success" : False,
                        "uuid" : param_hash,
                        "message" : f"Render {param_hash} already exists."
                    })
                else:
                    client.database.stable_jobs.insert_one(newrecord)
                    results.append({
                        "success" : True,
                        "uuid" : param_hash,
                        "message" : f"Render {param_hash} submitted successfully."
                    })          

        return dumps({"success" : True, "results" : results})

@app.route("/web/edit", methods=["POST"], defaults={"mode" : "edit"})
@app.route("/web/mutate", methods=["POST"], defaults={"mode" : "mutate"})
@requires_auth
def web_mutate(mode):
    # TODO: Rewrite this
    import random
    logger.info(mode)
    current_user = _request_ctx_stack.top.current_user
    # user_pulse(current_user)
    discord_id = int(current_user["sub"].split("|")[2])
    logger.info(f"Incoming {mode} job request from {discord_id}...")
    job = request.json.get("job")
    
    if mode == "edit":
        with get_database() as client:
            j = client.database.queue.find_one({"uuid" : job["uuid"], "status" : {"$in":["queued","rejected"]}})
            if not j:
                logger.info(f"{j['uuid']} is not valid.")
                return dumps({
                    "success" : False,
                    "message" : f"You cannot edit {j['uuid']}."
                })
            else:
                if j["author"] != discord_id:
                    logger.info(f"{j['uuid']} is not valid.")
                    return dumps({
                        "success" : False,
                        "message" : "You cannot edit someone else's job."
                    })

    try:
        set_seed = job["set_seed"]
    except:
        set_seed = random.randint(0, 2**32)
    if set_seed == -1:
        set_seed = random.randint(0, 2**32)
    if "agent_preference" in job:
        agent_preference = job["agent_preference"]
    else:
        agent_preference = "free"
    skip_augs = False
    if "skip_augs" in job:
        skip_augs = job["skip_augs"]
        
    if "gpu_preference" in job:
        gpu_preference = job["gpu_preference"]
    else:
        gpu_preference = "medium"

    if "tv_scale" in job:
        tv_scale = job["tv_scale"]
    else:
        tv_scale = 0

    if mode == "mutate":
        u = str(uuid.uuid4())
        timestamp = datetime.utcnow()

    if mode == "edit":
        u = job["uuid"]
        # timestamp = datetime.strptime(job["timestamp"]["$date"], '%Y-%m-%d %H:%M:%S.%f%Z')
        timestamp = datetime.utcnow()

    newrecord = {
        "uuid": u,
        "experimental" : True,
        "agent_preference" : agent_preference,
        "gpu_preference" : gpu_preference,
        "parent_uuid": job["uuid"],
        "render_type": "mutate",
        "nsfw": job["nsfw"],
        "author": discord_id,
        "status": "queued",
        "timestamp": timestamp,
        "origin": "web",
        # deprecated
        # "text_prompt": job["text_prompt"],
        # "model": "default",
        # "shape": "square",
        # "cut_schedule": "default",
        # Params
        "text_prompts": job["text_prompts"],
        "set_seed": set_seed,
        "seed": set_seed,
        "steps": job["steps"],
        "skip_steps": job["skip_steps"],
        "width_height": job["width_height"],
        "diffusion_model": job["diffusion_model"],
        "use_secondary_model": job["use_secondary_model"],
        "diffusion_sampling_mode": job["diffusion_sampling_mode"],
        "clip_models": job["clip_models"],
        "cutn_batches": job["cutn_batches"],
        "clip_guidance_scale": job["clip_guidance_scale"],
        "cut_overview": job["cut_overview"],
        "cut_ic_pow": job["cut_ic_pow"],
        "cut_innercut": job["cut_innercut"],
        "cut_icgray_p": job["cut_icgray_p"],
        "range_scale": job["range_scale"],
        "sat_scale": job["sat_scale"],
        "tv_scale": tv_scale,
        "clamp_grad": job["clamp_grad"],
        "clamp_max": job["clamp_max"],
        "eta": job["eta"],
        "use_horizontal_symmetry": job["use_horizontal_symmetry"],
        "use_vertical_symmetry": job["use_vertical_symmetry"],
        "transformation_percent": job["transformation_percent"],
        "randomize_class": job["randomize_class"],
        "skip_augs": skip_augs,
        "clip_denoised": job["clip_denoised"]
    }
    logger.info(mode)
    if mode=="mutate":
        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            queueCollection.insert_one(newrecord)
        return dumps({"success" : True, "new_record" : newrecord})
    
    if mode=="edit":
        logger.info(f"Editing job {u} by {str(discord_id)}...")
        with get_database() as client:
            client.database.queue.update_one({"uuid": u, "author" : discord_id}, {"$set": newrecord})
        return dumps({"success" : True, "new_record" : newrecord})

@app.route("/placeorder", methods=["POST"])
def placeorder():
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    author = request.form.get("author", type=int)
    # user_pulse(author)
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
        "timestamp": datetime.utcnow(),
    }
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        queueCollection.insert_one(newrecord)
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
                {"$unwind": {
                    "path": "$userdets",
                    "preserveNullAndEmptyArrays" : True
                }}
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
                        "nsfw": {"$nin": [True]},
                        "dominant_color.0": {"$gt": int(r) - int(range), "$lt": int(r) + int(range)},
                        "dominant_color.1": {"$gt": int(g) - int(range), "$lt": int(g) + int(range)},
                        "dominant_color.2": {"$gt": int(b) - int(range), "$lt": int(b) + int(range)},
                        "$or": [{"status": "complete"}, {"status": "archived"}],
                    }
                },
                {"$lookup": {"from": "users", "localField": "author", "foreignField": "user_id", "as": "userdets"}},
                {"$skip": (int(page) - 1) * int(amount)},
                {"$limit": int(amount)},
                {"$unwind": {
                    "path": "$userdets",
                    "preserveNullAndEmptyArrays" : True
                }}
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

def v3_postProcess(job_uuid, algo):
    import io, base64
    with get_database() as client:
        pieces = client.database.pieces

        job = pieces.find_one({"uuid": job_uuid})
        
        if algo == "disco":
            # TODO: get rid of "0_0" suffix
            # Inspect Document results
            # https://docarray.jina.ai/fundamentals/document/
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], job["filename"])
            png = os.path.join(app.config["UPLOAD_FOLDER"], f"{job_uuid}0_0.png")
            da = DocumentArray.load_binary(filepath)
            da[0].save_uri_to_file(png)
            da_tags = da[0].tags
            # logger.info(da_tags)
            # Annoyed that I can't figure this out.  Gonna write to filesystem
            # f = io.BytesIO(base64.b64decode(da[0].uri + '=='))
        
        if algo == "stable":
            png = os.path.join(app.config["UPLOAD_FOLDER"], f"{job_uuid}.png")

        
        
        ## Color Analysis
        color_thief = ColorThief(png)
        dominant_color = color_thief.get_color(quality=1)
        palette = color_thief.get_palette(color_count=5)

        pieces.update_one({"uuid": job_uuid}, {"$set": {"dominant_color": dominant_color, "palette": palette}})
        logger.info(f"🎨 Color analysis for {job_uuid} complete.")

        ## Indexing to Algolia
        if False:
            try:
                # TODO: Support array text_prompts
                algolia_index(job_uuid)
                pieces.update_one({"uuid": job_uuid}, {"$set": {"indexed": True}})
                logger.info(f"🔍 Job indexed to Algolia.")
            except:
                logger.info("Error trying to submit Algolia index.")
                pass
        
        ## Save thumbnails/jpg and upload to S3
        if BOT_USE_S3:
            try:
                # TODO: remove "0_0" suffix
                if algo == "disco":
                    upload_file_s3(png, BOT_S3_BUCKET, f"images/{job_uuid}0_0.png", {"ContentType": "image/png"})
                
                if algo == "stable":
                    upload_file_s3(png, BOT_S3_BUCKET, f"images/{job_uuid}.png", {"ContentType": "image/png"})
                
                s3_thumbnail(job_uuid, 64, algo=algo)
                s3_thumbnail(job_uuid, 128, algo=algo)
                s3_thumbnail(job_uuid, 256, algo=algo)
                s3_thumbnail(job_uuid, 512, algo=algo)
                s3_thumbnail(job_uuid, 1024, algo=algo)
                s3_jpg(job_uuid, algo=algo)
                pieces.update_one({"uuid": job_uuid}, {"$set": {"thumbnails": [64, 128, 256, 512, 1024], "jpg": True}})
                logger.info(f"👍 Thumbnails uploaded to s3 for {job_uuid}")
                logger.info(f"🖼️ JPEG version for {job_uuid} saved to s3")

            except Exception as e:
                logger.error(e)

            payload = {
                "status": "complete",
                "time_completed" : datetime.utcnow(),
                "results" : None    # TODO - Remove
            }
                            
            ## Mark as postprocessing complete
            if algo == "disco":
                payload["discoart_tags"] = da_tags
            
            pieces.update_one({"uuid": job_uuid}, {"$set": payload})

def postProcess(job_uuid, algo):
    import io, base64
    with get_database() as client:
        if algo == "disco":
            queue = client.database.queue
        
        if algo == "stable":
            queue = client.database.stable_jobs

        job = queue.find_one({"uuid": job_uuid})
        
        if algo == "disco":
            # TODO: get rid of "0_0" suffix
            # Inspect Document results
            # https://docarray.jina.ai/fundamentals/document/
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], job["filename"])
            png = os.path.join(app.config["UPLOAD_FOLDER"], f"{job_uuid}0_0.png")
            da = DocumentArray.load_binary(filepath)
            da[0].save_uri_to_file(png)
            da_tags = da[0].tags
            # logger.info(da_tags)
            # Annoyed that I can't figure this out.  Gonna write to filesystem
            # f = io.BytesIO(base64.b64decode(da[0].uri + '=='))
        
        if algo == "stable":
            png = os.path.join(app.config["UPLOAD_FOLDER"], f"{job_uuid}.png")

        
        
        ## Color Analysis
        color_thief = ColorThief(png)
        dominant_color = color_thief.get_color(quality=1)
        palette = color_thief.get_palette(color_count=5)

        queue.update_one({"uuid": job_uuid}, {"$set": {"dominant_color": dominant_color, "palette": palette}})
        logger.info(f"🎨 Color analysis for {job_uuid} complete.")

        ## Indexing to Algolia
        if False:
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
                if algo == "disco":
                    upload_file_s3(png, BOT_S3_BUCKET, f"images/{job_uuid}0_0.png", {"ContentType": "image/png"})
                
                if algo == "stable":
                    upload_file_s3(png, BOT_S3_BUCKET, f"images/{job_uuid}.png", {"ContentType": "image/png"})
                
                s3_thumbnail(job_uuid, 64, algo=algo)
                s3_thumbnail(job_uuid, 128, algo=algo)
                s3_thumbnail(job_uuid, 256, algo=algo)
                s3_thumbnail(job_uuid, 512, algo=algo)
                s3_thumbnail(job_uuid, 1024, algo=algo)
                s3_jpg(job_uuid, algo=algo)
                queue.update_one({"uuid": job_uuid}, {"$set": {"thumbnails": [64, 128, 256, 512, 1024], "jpg": True}})
                logger.info(f"👍 Thumbnails uploaded to s3 for {job_uuid}")
                logger.info(f"🖼️ JPEG version for {job_uuid} saved to s3")

            except Exception as e:
                logger.error(e)
            
            ## Mark as postprocessing complete
            if algo == "disco":
                results = queue.update_one(
                    {"uuid": job_uuid}, {"$set": {"status": "complete", "time_completed" : datetime.utcnow(), "discoart_tags" : da_tags, "results" : None}}
                )
            
            if algo == "stable":
                results = queue.update_one(
                    {"uuid": job_uuid}, {"$set": {"status": "complete", "time_completed" : datetime.utcnow()}}
                )

@app.route("/web/uploadart", methods=["POST"])
@requires_auth
def web_uploadart():
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    logger.info(f"🎨 Art upload from {discord_id}")
    if "file" not in request.files:
        logger.info(f"🎨 No file detected.  Exiting.")
        return dumps({
            "success" : False,
            "message" : "No file received."
        })
    else:
        file = request.files["file"]
        if file and allowed_file(file.filename):
            filename = secure_filename(f"{str(discord_id)}-{file.filename}")
            filepath = os.path.join(f'{app.config["UPLOAD_FOLDER"]}/user_uploads', filename)
            file.save(filepath)
            logger.info(f"🎨 File saved to {filename}")
            # Extract
            da = DocumentArray.load_binary(filepath)
            for i, document in enumerate(da):
                tags = document.tags
                name_docarray = tags["name_docarray"]
                job_uuid = f'{str(discord_id)}-{name_docarray}_{str(i)}'
                logger.info(f"User-submitted job UUID: {job_uuid}")
                png_filename = f"{str(discord_id)}-{name_docarray}_{str(i)}.png"
                pngpath = os.path.join(f'{app.config["UPLOAD_FOLDER"]}/user_uploads', png_filename)
                logger.info(f"Saving PNG {pngpath}")
                document.save_uri_to_file(pngpath)
                process_upload(job_uuid, pngpath, png_filename)
                # logger.info(tags)
                record = {
                    "private": True,
                    "uuid": job_uuid,
                    "render_type": "upload",  # important
                    "origin":"upload",
                    "nsfw": False,
                    "agent_id": "external",
                    "author": discord_id,
                    "status": "archived",
                    "timestamp": datetime.utcnow(),
                    "last_preview": datetime.utcnow(),
                    "gpu_preference" : "external",
                    "width_height": tags["width_height"],
                    "steps": tags["steps"],
                    "clip_models": tags["clip_models"],
                    "use_secondary_model": tags["use_secondary_model"],
                    "diffusion_model": tags["diffusion_model"],
                    "text_prompts":tags["text_prompts"],
                    "cut_overview":tags["cut_overview"],
                    "cut_innercut":tags["cut_innercut"],
                    "cut_ic_pow":tags["cut_ic_pow"],
                    "cut_icgray_p":tags["cut_icgray_p"],
                    "skip_steps": tags["skip_steps"],
                    "init_scale":tags["init_scale"],
                    "clip_guidance_scale": tags["clip_guidance_scale"],
                    "tv_scale": tags["tv_scale"],
                    "range_scale": tags["range_scale"],
                    "sat_scale": tags["sat_scale"],
                    "cutn_batches": tags["cutn_batches"],
                    "diffusion_sampling_mode": "ddim",
                    "perlin_init": tags["perlin_init"],
                    "perlin_mode": tags["perlin_mode"],
                    "eta": tags["eta"],
                    "clamp_grad" : tags["clamp_grad"],
                    "clamp_max": tags["clamp_max"],
                    "randomize_class" : tags["randomize_class"],
                    "clip_denoised" : tags["clip_denoised"],
                    "rand_mag" : tags["rand_mag"],
                    "use_vertical_symmetry": tags["use_vertical_symmetry"],
                    "use_horizontal_symmetry": tags["use_horizontal_symmetry"],
                    "transformation_percent":[0.09],
                    "skip_augs": False,
                    "on_misspelled_token": "ignore",
                    "text_clip_on_cpu": False,
                    "discoart_tags" : tags
                }
                logger.info(record)
                with get_database() as client:
                    client.database.queue.update_one({"uuid": job_uuid, "author" : discord_id}, {
                        "$set": record
                    }, upsert=True)
                    # client.database.queue.insert_one(record)
                    # da[0].save_uri_to_file(png)
                    # da_tags = da[0].tags
    return dumps({
        "success" : True
    })

def process_upload(job_uuid, filepath, filename):
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

@app.route("/stable/deliverorder", methods=["POST"])
def stable_deliver():
    logger.info("🐴")
    agent_id = request.form.get("agent_id")
    agent_version = request.form.get("agent_version")
    job_uuid = request.form.get("uuid")
    logger.info(f"🐴 {agent_id} delivering {job_uuid}")
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
        filename = secure_filename(f"{job_uuid}.png")
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
    else:
        return dumps({
            "success" : False,
            "message" : "Unexpected file type."
        })
    
    # Since payload is saved, update job record.
    with get_database() as client:
        client.database.stable_jobs.update_one(
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
        postProcess(job_uuid, "stable")
        # Give agent a point
        with get_database() as client:
            results = client.database.agents.find_one({"agent_id": agent_id})
            score = results.get("score")
            if not score:
                score = 1
            else:
                score += 1
            results = client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"score": score}})

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
        postProcess(job_uuid, "disco")
        # Give agent a point
        with get_database() as client:
            results = client.database.agents.find_one({"agent_id": agent_id})
            score = results.get("score")
            if not score:
                score = 1
            else:
                score += 1
            results = client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"score": score}})

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

def agent_pulse(agent_info, mode):
    """Updates DB State of Agent"""
    with get_database() as client:
        client.database.agents.update_one({"agent_id": agent_info['agent_id']},
            {"$set": {
                "last_seen": datetime.utcnow(),
                "mode": mode,
                "idle_time": int(agent_info["idle_time"]),
                "bot_version": str(agent_info["bot_version"]),
                "gpu": agent_info["gpu_record"],
                "agent_version" : agent_info["agent_version"],
                "algo" : "stable",
                "start_time" : agent_info["start_time"],
                "boot_time" : agent_info["boot_time"],
                "free_space" : agent_info["free_space"],
                "used_space" : agent_info["used_space"],
                "total_space" : agent_info["total_space"],
                "memory" : agent_info["memory_record"]
                }
            }
        )

def agent_parse(agent_id, request):
    """Returns info about agent request for work"""
    idle_time = request.form.get("idle_time")
    bot_version = request.form.get("bot_version")
    agent_version = request.form.get("agent_version")
    start_time = request.form.get("start_time")
    boot_time = request.form.get("boot_time")
    try:
        algo = request.form.get("algo")
    except:
        algo = "UNKNOWN"
    try:
        boot_time = datetime.strptime(boot_time, '%Y-%m-%d %H:%M:%S.%f')
    except:
        boot_time = None
    try:
        free_space = int(request.form.get("free_space"))
        used_space = int(request.form.get("used_space"))
        total_space = int(request.form.get("total_space"))
    except:
        free_space = 0
        used_space = 0
        total_space = 0
    try:
        m = request.form.get("memory")
        memory_record = json.loads(m)
    except:
        memory_record = request.form.get("memory")
    owner = request.form.get("owner")
    gpus = request.form.get("gpus")
    gpu_size = "small"
    if type(gpus) is str:
        try:
            gpu_record = json.loads(gpus)
            vram = gpu_record["mem_total"]
            if vram>13000:
                gpu_size = "medium"
            if vram>25000:
                gpu_size = "large"
            if vram>50000:
                gpu_size = "titan"
        except:
            gpu_record = None
    else:
        gpu_record = None

    return {
        "agent_id" : agent_id,
        "vram" : vram,
        "algo" : algo,
        "idle_time" : idle_time,
        "bot_version" : bot_version,
        "agent_version" : agent_version,
        "start_time" : start_time,
        "boot_time" : boot_time,
        "free_space" : free_space,
        "used_space" : used_space,
        "total_space" : total_space,
        "memory_record" : memory_record,
        "gpu_record" : gpu_record,
        "owner" : owner,
        "gpus" : gpus,
        "gpu_size" : gpu_size
    }

@app.route("/v3/deliveresrgan", methods=["POST"])
def v3_deliver_esrgan():
    agent_id = request.form.get("agent_id")
    algo = request.form.get("algo")
    agent_version = request.form.get("agent_version")
    job_uuid = request.form.get("uuid")
    augid = request.form.get("augid")
    logger.info(f"🚚 {agent_id} ({algo}) delivering {job_uuid} augmentation {augid}")
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
        filename = secure_filename(f"{augid}.png")
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
        logger.info(f"🤘 {filepath} saved.")
        if BOT_USE_S3:
            try:
                upload_file_s3(filepath, BOT_S3_BUCKET, f"images/{augid}.png", {"ContentType": "image/png"})
                logger.info(f"🖼️ Upscale version for {job_uuid} {augid} saved to s3")
                # Make JPG
                algo = "stable"
                s3_jpg(augid, algo=algo)
                s3_thumbnail(augid, 64, algo=algo)
                s3_thumbnail(augid, 128, algo=algo)
                s3_thumbnail(augid, 256, algo=algo)
                s3_thumbnail(augid, 512, algo=algo)
                s3_thumbnail(augid, 1024, algo=algo)
                logger.info(f"🖼️ JPEG and Thumbnails made for {augid} and saved to s3")
                # Since payload is saved, update job record.
                with get_database() as client:
                    jobs = list(client.database.pieces.aggregate([
                        {
                            "$unwind" : {
                                "path": "$augs",
                                "includeArrayIndex": 'augIndex',
                                "preserveNullAndEmptyArrays": True
                            }
                        },{
                            "$match" : {
                                "uuid" : job_uuid,
                                "augs.augid" : augid,
                                "augs.status" : "processing",
                                "augs.agent_id" : agent_id
                            }
                        }]))
                    if len(jobs) > 0:
                        augIndex = jobs[0]["augIndex"]
                        client.database.pieces.update_one({
                            "uuid" : job_uuid
                        },{
                            "$set": {
                                f"augs.{augIndex}.status" : "complete"
                            }
                        })
                        logger.info("✅ Piece marked as augmented.")
                        return dumps({
                            "success" : True,
                            "message" : "Delivery received!",
                            "duration" : duration
                        })
                    else:
                        logger.info("❌ Unexpected delivery.  Ignoring.")
                        import traceback
                        tb = traceback.format_exc()
                        logger.error(tb)
                        return
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                logger.error(tb)

    else:
        return dumps({
            "success" : False,
            "message" : "Unexpected file type."
        })
    
    
                
    try:
        # Give agent a point
        with get_database() as client:
            results = client.database.agents.find_one({"agent_id": agent_id})
            score = results.get("score")
            if not score:
                score = 1
            else:
                score += 1
            results = client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"score": score}})

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



@app.route("/v3/deliverorder", methods=["POST"])
def v3_deliver_order():
    agent_id = request.form.get("agent_id")
    algo = request.form.get("algo")
    agent_version = request.form.get("agent_version")
    job_uuid = request.form.get("uuid")
    logger.info(f"🚚 {agent_id} ({algo}) delivering {job_uuid}")
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
        filename = secure_filename(f"{job_uuid}.png")
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
    else:
        return dumps({
            "success" : False,
            "message" : "Unexpected file type."
        })
    
    # Since payload is saved, update job record.
    with get_database() as client:
        q = {"agent_id": agent_id, "uuid": job_uuid}
        piece = client.database.queue.find_one(q)
        if piece:
            client.database.pieces.insert_one(piece)
            client.database.queue.delete_many(q)
            logger.info("✅ Delivery moved to pieces collection.")
        else:
            logger.info("❌ Unexpected delivery.  Ignoring.")
            import traceback
            tb = traceback.format_exc()
            logger.error(tb)
            return
                
    try:
        v3_postProcess(job_uuid, algo)
        # Give agent a point
        with get_database() as client:
            results = client.database.agents.find_one({"agent_id": agent_id})
            score = results.get("score")
            if not score:
                score = 1
            else:
                score += 1
            results = client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"score": score}})

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

@app.route("/v3/takeorder/<agent_id>", methods=["POST"])
def v3_takeorder(agent_id):
    """Take a render order
    
    `agent_id` - Agent ID
    """
    with get_database() as client:
        agent = client.database.agents.find_one({"agent_id": agent_id})
        if not agent:
            logger.info(f"Unknown agent looking for work: {agent_id}")
            return dumps({"message": f"I don't know a {agent_id}.  Did you not register?", "success": False})

        agent_info = agent_parse(agent_id, request)
        mode = "awake"
        logger.info(f"👀 {agent_id} ({agent_info['vram']} VRAM aka {agent_info['gpu_size']}) owned by {agent_info['owner']} looking for work ({agent_info['algo']}) - Idle time: {agent_info['idle_time']}...")
        agent_pulse(agent_info, mode)
        
        # First, see if there are commands to relay before jobs...
        if "command" in agent:
            command = agent["command"]
            logger.info(f"🤖 Command for {agent_id} received: {command}")
            with get_database() as client:
                client.database.agents.update_one({"agent_id": agent_id}, {"$unset": { "command" : 1 }})
            return dumps({
                "command" : command
            })
        if agent_info['algo'] == "stable":
            with get_database() as client:
                # 1) See if already assigned job
                job = client.database.queue.find_one({
                    "status": "processing",
                    "agent_id": agent_id,
                })
                if agent_info['gpu_size'] == "small":
                    pixels = (512 * 704)
                if agent_info['gpu_size'] == "medium":
                    pixels = (1024 * 512)
                if agent_info['gpu_size'] == "large":
                    pixels = (1536 * 1536)
                if agent_info['gpu_size'] == "titan":
                    pixels = (1536 * 1536 * 2)
                # 2) Check for priority jobs first
                # if not job:
                #     job = None
                #     query = {
                #         "status": "queued", 
                #         "algo" : agent_info['algo'],
                #         "$and" : [
                #             {"$or" : [{"priority" : True},{"userdets.user_str":"398901736649261056"}]},
                #             {"$or" : gpuq}
                #         ]
                #     }
                #     jobs = list(client.database.queue.find(query))
                #     logger.info(f"{len(jobs)} priority jobs found.")
                #     if len(jobs) > 0:
                #         job = jobs[0]

                # 3) Check for normal priority jobs
                if not job:
                    query = {
                        "status": "queued",
                        "algo" : agent_info['algo'],
                        "pixels" : {"$lte" : pixels}
                    }
                    up_next = list(client.database.queue.aggregate([
                        { "$set" : {
                            "pixels": {
                                "$multiply":[
                                    {"$arrayElemAt" : ["$width_height",0]},
                                    {"$arrayElemAt" : ["$width_height",1]}
                                ]
                            }
                            }
                        },
                        {"$match" : query}
                    ]))   # TODO: Restore up_next logic
                    queueCount = len(up_next)
                    # logger.info(f"{queueCount} renders in queue.")
                    if queueCount > 0:
                        job = up_next[0]
                
                # If work found:
                if job:
                    client.database.queue.update_one({"uuid": job.get("uuid")}, {"$set": {
                        "status": "processing",
                        "agent_id": agent_id,
                        "last_preview": datetime.utcnow(),
                        "percent": 0,       # TODO: Remove?
                        "gpustats": None    # TODO: Remove?
                    }})

                    client.database.agents.update_one({"agent_id": agent_id}, {"$set": {
                        "mode": "working",
                        "idle_time": 0
                    }})

                    return dumps({
                        "success": True,
                        "message": f"Your current job is {job.get('uuid')}.",
                        "uuid": job.get("uuid"),
                        "details": json.loads(dumps(job))
                    })
                else:
                    # See if we need to dream
                    if int(agent_info["idle_time"]) > 30:
                        mode = "dreaming"
                    else:
                        mode = "awake"
                    
                    # mode = "dreaming"

                    # No work, see if it's dream time:
                    # logger.info("No user jobs in queue...")
                    if mode == "dreaming":
                        client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"mode": "dreaming", "idle_time": 0}})
                        logger.info("Dream Job incoming.")
                        d = v3_dream(agent_info)
                        return dumps({
                        "success": True,
                            "message": f"Your current job is {d.get('uuid')}.",
                            "uuid": d.get("uuid"),
                            "details": d
                        })
                    return dumps({"message": f"Could not secure a user job.", "success": False})
                    # if mode == "awake":
                    #     return dumps({"message": f"Could not secure a user job.", "success": False})

            return dumps({"message": f"No queued jobs at this time.", "success": False})

        if agent_info['algo'] == "esrgan":
            # First see if a job is already in progress:
            j = list(client.database.pieces.aggregate([
                {
                    "$unwind" : {
                        "path": "$augs",
                        "includeArrayIndex": 'augIndex',
                        "preserveNullAndEmptyArrays": True
                    }
                },{
                    "$match" : {
                        "augs.status" : "processing",
                        "augs.agent_id" : agent_id
                    }
                }]))
            
            # Next see if any jobs are waiting
            if len(j)==0:
                j = list(client.database.pieces.aggregate([
                {
                    "$unwind" : {
                        "path": "$augs",
                        "includeArrayIndex": 'augIndex',
                        "preserveNullAndEmptyArrays": True
                    }
                },{
                    "$match" : {
                        "augs.status" : "requested"
                    }
                }]))
            if len(j)>0:
                j = j[0]
                augIndex = j["augIndex"]
                augs = j["augs"]
                augs["agent_id"] = agent_id
                augs["status"] = "processing"
                client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time": 0}})
                client.database.pieces.update_one({"uuid": j.get("uuid")}, {"$set": {
                    f"augs.{augIndex}" : augs
                }})

                return dumps({
                    "success": True,
                    "message": f"Your current job is {j.get('uuid')}.",
                    "uuid": j.get("uuid"),
                    "details": json.loads(dumps(augs))
                })
            else:
                return dumps({"message": f"No queued jobs at this time.", "success": False})

@app.route("/stable/takeorder/<agent_id>", methods=["POST"])
def stable_takeorder(agent_id):
    # Make sure agent is registered...
    with get_database() as client:
        agent = client.database.agents.find_one({"agent_id": agent_id})
        if not agent:
            logger.info(f"Unknown agent looking for work: {agent_id}")
            return dumps({"message": f"I don't know a {agent_id}.  Did you not register?", "success": False})
        else:
            idle_time = request.form.get("idle_time")
            bot_version = request.form.get("bot_version")
            agent_version = request.form.get("agent_version")
            start_time = request.form.get("start_time")
            boot_time = request.form.get("boot_time")
            try:
                boot_time = datetime.strptime(boot_time, '%Y-%m-%d %H:%M:%S.%f')
            except:
                boot_time = None
            try:
                free_space = int(request.form.get("free_space"))
                used_space = int(request.form.get("used_space"))
                total_space = int(request.form.get("total_space"))
            except:
                free_space = 0
                used_space = 0
                total_space = 0
            try:
                m = request.form.get("memory")
                memory_record = json.loads(m)
            except:
                memory_record = request.form.get("memory")
            owner = request.form.get("owner")
            gpus = request.form.get("gpus")
            vram = 0
            gpu_size = "small"
            if type(gpus) is str:
                try:
                    gpu_record = json.loads(gpus)
                    vram = gpu_record["mem_total"]
                    if vram>13000:
                        gpu_size = "medium"
                    if vram>25000:
                        gpu_size = "large"
                    if vram>50000:
                        gpu_size = "titan"
                except:
                    gpu_record = None
            else:
                gpu_record = None
            
            mode = "awake"
            with get_database() as client:
                client.database.agents.update_one({"agent_id": agent_id}, {"$set": {
                    "mode": mode,
                    "idle_time": int(idle_time),
                    "bot_version": str(bot_version),
                    "gpu": gpu_record,
                    "agent_version" : agent_version,
                    "algo" : "stable",
                    "start_time" : start_time,
                    "boot_time" : boot_time,
                    "free_space" : free_space,
                    "used_space" : used_space,
                    "total_space" : total_space,
                    "memory" : memory_record
                    }
                })
            pulse(agent_id=agent_id)
            logger.info(f"🐎 {agent_id} ({vram} VRAM aka {gpu_size}) owned by {owner} looking for work - Idle time: {idle_time}...")
            logger.info(dumps(request.form))
            if "command" in agent:
                command = agent["command"]
                logger.info(f"🤖 Command for {agent_id} received: {command}")
                with get_database() as client:
                    client.database.agents.update_one({"agent_id": agent_id}, {"$unset": { "command" : 1 }})
                return dumps({
                    "command" : command
                })
            
            if int(idle_time) > 30:
                mode = "dreaming"
            else:
                mode = "awake"
            
        # Inform agent if there's already a job assigned...
        with get_database() as client:
            queueCollection = client.database.get_collection("stable_jobs")
            query = {
                "status": "processing",
                "agent_id": agent_id,
            }
            jobCount = queueCollection.count_documents(query)
            if jobCount > 0:
                # Update status
                client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time": 0}})
                jobs = queueCollection.find_one(query)
                logger.info("working")
                return dumps({"message ": f"You already have a job.  (Job '{jobs.get('uuid')}')", "uuid": jobs.get("uuid"), "details": json.loads(dumps(facelift(jobs))), "success": True})
            else:
                job = None
                # Check for priority jobs first
                query = {
                    "status": "queued", 
                    "$and" : [
                        {"$or" : [{"priority" : True},{"userdets.user_str":"398901736649261056"}]},
                        {"$or" : [{"gpu_preference" : "any"},{"gpu_preference" : gpu_size}]}
                    ]
                }
                jobs = list(client.database.stable_jobs.find(query))
                logger.info(f"{len(jobs)} priority jobs found.")
                if len(jobs) > 0:
                    job = jobs[0]
                else:
                    query = {
                        "status": "queued",
                        "$or" : [{"gpu_preference" : "any"},{"gpu_preference" : gpu_size}]
                    }
                    up_next = list(client.database.stable_jobs.find(query))
                    queueCount = len(up_next)
                    # logger.info(f"{queueCount} renders in queue.")
                    if queueCount > 0:
                        # Work found
                        job = up_next[0]
                if job:
                    results = queueCollection.update_one({"uuid": job.get("uuid")}, {"$set": {"status": "processing", "agent_id": agent_id, "last_preview": datetime.utcnow()}})
                    count = results.modified_count
                    if count > 0:
                        # Set initial progress
                        e = {"type": "progress", "agent": agent_id, "job_uuid": job.get("uuid"), "percent": 0, "gpustats": None}
                        # event(e)
                        client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time": 0}})
                        return dumps({"message": f"Your current job is {job.get('uuid')}.", "uuid": job.get("uuid"), "details": json.loads(dumps(facelift(job))), "success": True})
                else:
                    # No work, see if it's dream time:
                    # logger.info("No user jobs in queue...")
                    return dumps({"message": f"Could not secure a user job.", "success": False})
                    # if mode == "awake":
                    #     return dumps({"message": f"Could not secure a user job.", "success": False})
                    # if mode == "dreaming":
                    #     logger.info("Dream Job incoming.")
                    #     d = dream_v2(agent_id, gpu_size)
                    #     client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"mode": "dreaming", "idle_time": 0}})
                    #     return dumps(d)

        return dumps({"message": f"No queued jobs at this time.", "success": False})

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
            agent_discoart_version = request.form.get("agent_discoart_version")
            start_time = request.form.get("start_time")
            boot_time = request.form.get("boot_time")
            try:
                boot_time = datetime.strptime(boot_time, '%Y-%m-%d %H:%M:%S.%f')
            except:
                boot_time = None
            try:
                free_space = int(request.form.get("free_space"))
                used_space = int(request.form.get("used_space"))
                total_space = int(request.form.get("total_space"))
            except:
                free_space = 0
                used_space = 0
                total_space = 0
            try:
                m = request.form.get("memory")
                memory_record = json.loads(m)
            except:
                memory_record = request.form.get("memory")
            owner = request.form.get("owner")
            gpus = request.form.get("gpus")
            vram = 0
            gpu_size = "small"
            if type(gpus) is str:
                try:
                    gpu_record = json.loads(gpus)
                    vram = gpu_record["mem_total"]
                    if vram>13000:
                        gpu_size = "medium"
                    if vram>25000:
                        gpu_size = "large"
                    if vram>50000:
                        gpu_size = "titan"
                except:
                    gpu_record = None
            else:
                gpu_record = None
            
            mode = "awake"
            with get_database() as client:
                client.database.agents.update_one({"agent_id": agent_id}, {"$set": {
                    "mode": mode,
                    "idle_time": int(idle_time),
                    "bot_version": str(bot_version),
                    "gpu": gpu_record,
                    "agent_discoart_version" : agent_discoart_version,
                    "start_time" : start_time,
                    "boot_time" : boot_time,
                    "free_space" : free_space,
                    "used_space" : used_space,
                    "total_space" : total_space,
                    "memory" : memory_record
                    }
                })
            pulse(agent_id=agent_id)
            logger.info(f"{agent_id} ({vram} VRAM aka {gpu_size}) owned by {owner} looking for work - Idle time: {idle_time}...")
            logger.info(dumps(request.form))
            if "command" in agent:
                command = agent["command"]
                logger.info(f"🤖 Command for {agent_id} received: {command}")
                with get_database() as client:
                    client.database.agents.update_one({"agent_id": agent_id}, {"$unset": { "command" : 1 }})
                return dumps({
                    "command" : command
                })
            
            if int(idle_time) > 30:
                mode = "dreaming"
            else:
                mode = "awake"
            
        # Inform agent if there's already a job assigned...
        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            query = {
                "status": "processing",
                "agent_id": agent_id,
            }
            jobCount = queueCollection.count_documents(query)
            if jobCount > 0:
                # Update status
                client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time": 0}})
                jobs = queueCollection.find_one(query)
                logger.info("working")
                return dumps({"message ": f"You already have a job.  (Job '{jobs.get('uuid')}')", "uuid": jobs.get("uuid"), "details": json.loads(dumps(facelift(jobs))), "success": True})
            else:
                job = None
                # Check for priority jobs first
                query = {
                    "status": "queued", 
                    "$and" : [
                        {"$or" : [{"priority" : True},{"userdets.user_str":"398901736649261056"}]},
                        {"$or" : [{"gpu_preference" : "any"},{"gpu_preference" : gpu_size}]}
                    ]
                }
                jobs = list(client.database.vw_next_up.find(query))
                logger.info(f"{len(jobs)} priority jobs found.")
                if len(jobs) > 0:
                    job = jobs[0]
                else:
                    query = {
                        "status": "queued",
                        "$or" : [{"gpu_preference" : "any"},{"gpu_preference" : gpu_size}]
                    }
                    up_next = list(client.database.vw_next_up.find(query))
                    queueCount = len(up_next)
                    # logger.info(f"{queueCount} renders in queue.")
                    if queueCount > 0:
                        # Work found
                        job = up_next[0]
                if job:
                    results = queueCollection.update_one({"uuid": job.get("uuid")}, {"$set": {"status": "processing", "agent_id": agent_id, "last_preview": datetime.utcnow()}})
                    count = results.modified_count
                    if count > 0:
                        # Set initial progress
                        e = {"type": "progress", "agent": agent_id, "job_uuid": job.get("uuid"), "percent": 0, "gpustats": None}
                        # event(e)
                        client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time": 0}})
                        return dumps({"message": f"Your current job is {job.get('uuid')}.", "uuid": job.get("uuid"), "details": json.loads(dumps(facelift(job))), "success": True})
                else:
                    # No work, see if it's dream time:
                    # logger.info("No user jobs in queue...")
                    if mode == "awake":
                        return dumps({"message": f"Could not secure a user job.", "success": False})
                    if mode == "dreaming":
                        logger.info("Dream Job incoming.")
                        d = dream_v2(agent_id, gpu_size)
                        client.database.agents.update_one({"agent_id": agent_id}, {"$set": {"mode": "dreaming", "idle_time": 0}})
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
                # logger.info(f"{queueCount} priority jobs in queue.")

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

                    results = queueCollection.update_one({"uuid": job.get("uuid")}, {"$set": {"status": "processing", "agent_id": agent_id, "last_preview": datetime.utcnow()}})
                    count = results.modified_count
                    if count > 0:
                        e = {"type": "progress", "agent": agent_id, "job_uuid": job.get("uuid"), "percent": 0, "gpustats": None}
                        # event(e)
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

def v3_dream(agent_info):
    import random
    import dd_prompt_salad
    
    # Ensure it's a unique job
    exists = True
    while exists:
        width_height = [512,512]
        if agent_info['gpu_size'] == "small":
            width_height = random.sample([[704,512], [512,704], [512,512]], 1)[0]
        if agent_info['gpu_size'] == "medium":
            width_height = random.sample([[704,512], [512,704], [512,512]], 1)[0]
        if agent_info['gpu_size'] == "large":
            width_height = random.sample([[1024,512], [512,1024], [1536,512], [512,1536]], 1)[0]

        weights_hash = "fe4efff1e174c627256e44ec2991ba279b3816e364b49f9be2abc0b3ff3f8556" # 1.4
        seed = random.randint(0, 2**32)
        eta = 0.0
        scale = random.sample([6,7,8,9,10,11,12,13,14], 1)[0]
        steps = 50
        # template = "A beautiful landscape, art by {progrock/artist}"
        dream = getOldestDream()
        template = dream.get("prompt")
        author_id = dream.get("author_id")
        prompt = dd_prompt_salad.make_random_prompt(amount=1, prompt_salad_path="prompt_salad", template=template)[0]
        prompt_hash = str(hashlib.sha256(prompt.encode('utf-8')).hexdigest())
        params = {
            "weights" : weights_hash,
            "n_samples" : 1,
            "prompt" : prompt,
            "seed" : seed,
            "steps": steps,
            "eta" : eta,
            "scale" : scale,
            "width_height" : width_height
        }
        ns_params = SimpleNamespace(**params)
        p = json.dumps(ns_params.__dict__, indent = 4)
        param_hash = str(hashlib.sha256(p.encode('utf-8')).hexdigest())
        with get_database() as client:
            j = client.database.vw_all.find_one({"uuid" : param_hash})
            if j:
                exists = True
            else:
                exists = False
    
    # Make Job
    timestamp = datetime.utcnow()
    newrecord = {
        "agent_id" : agent_info['agent_id'],
        "weights" : weights_hash,
        "uuid" : param_hash,
        "preferred_image" : param_hash,
        # "author" : 977198605221912616,
        "author" : author_id,
        "timestamp": timestamp,
        "hide" : False,
        "nsfw" : False,
        "private" : False,
        "status" : "processing",
        "origin" : "dream",
        "prompt_hash" : prompt_hash,
        "algo" : "stable",
        "width_height" : width_height,
        "params" : ns_params.__dict__
    }
    with get_database() as client:
        client.database.queue.insert_one(newrecord)
    logger.info(newrecord)
    return newrecord

def dream_v2(agent_id, gpu_size):
    import dd_prompt_salad
    import random
    job_uuid = uuid.uuid4()
    dream = getOldestDream()
    mem_total = 0
    with get_database() as client:
        agent = client.database.agents.find_one({"agent_id": agent_id})
        gpu = agent.get("gpu")
        mem_total = gpu["mem_total"]
    if not dream:
        return
    prompt = dream.get("prompt")
    is_nightmare = dream.get("is_nightmare")
    if is_nightmare:
        render_type = "nightmare"
        nsfw = True
    else:
        render_type = "dream"
        nsfw = False
    salad = dd_prompt_salad.make_random_prompt(amount=1, prompt_salad_path="prompt_salad", template=prompt)[0]
    text_prompt = salad
    logger.info(text_prompt)
    author_id = dream.get("author_id")
    # Small Default
    w_h = random.sample([[1024,512], [512,2048], [1024,1024], [1280,768], [768,1280]], 1)[0]
    clip_models = [
        "ViT-B-32::openai",
        "ViT-B-16::openai",
        "RN50::openai"
    ]
    # Medium
    if gpu_size == "medium":
        w_h = random.sample([[2048,512], [512,2048], [1024,1024], [1280,768], [768,1280]], 1)[0]
        clip_models = [
            "ViT-B-32::openai",
            "ViT-B-16::openai",
            "ViT-L-14-336::openai"
        ]
    # Large
    if gpu_size == "large":
        w_h = random.sample([[2048,512], [512,2048], [1024,1024], [1280,768], [768,1280]], 1)[0]
        clip_models = [
            "ViT-B-32::openai",
            "ViT-B-16::openai",
            "RN50x64::openai",
            "ViT-L-14-336::openai"
        ]
    
    # Titan
    if gpu_size == "large":
        w_h = random.sample([[2048,1024], [1024,2048], [2048,2048], [1024,1024], [1536,1536]], 1)[0]
        clip_models = [
            "ViT-B-32::openai",
            "ViT-B-16::openai",
            "RN50x64::openai",
            "ViT-L-14-336::openai"
        ]
            
    steps = random.sample([200, 300], 1)[0]
    cut_ic_pow = random.sample([1, 5, 10], 1)[0]
    clip_guidance_scale = random.sample([5000, 7500, 10000, 15000, 20000], 1)[0]
    cutn_batches = random.sample([4, 6], 1)[0]
    use_horizontal_symmetry = False
    cut_overview="[12]*400+[4]*600"
    cut_innercut="[4]*400+[12]*600"
    cut_ic_pow=1.
    cut_icgray_p="[0.2]*400+[0]*600"
    sat_scale = random.sample([0, 0.5], 1)[0]
    diffusion_model = dream.get("diffusion_model")
    if not diffusion_model:
        diffusion_model = "512x512_diffusion_uncond_finetune_008100"

    if diffusion_model in [ "512x512_diffusion_uncond_finetune_008100", "256x256_diffusion_uncond"]:
        use_secondary_model = True
    else:
        use_secondary_model = False
        cut_overview="[12]*400+[4]*600"
        cut_innercut="[4]*400+[12]*600"
        cut_ic_pow=1.
        cut_icgray_p="[0.2]*400+[0]*600"
    # Special Isometric settings
    if dream.get("diffusion_model") in [ "IsometricDiffusionRevart512px"]:
        if mem_total > 20000:
            clip_models = [
                "ViT-B-32::openai",
                "ViT-B-16::openai",
                "RN50x64::openai",
                "ViT-L-14-336::openai"
            ]
        else:
            clip_models = [
                "ViT-B-32::openai",
                "ViT-B-16::openai",
                "ViT-L-14-336::openai"
            ]
        use_secondary_model = False

    # Special Portait settings
    if diffusion_model in [
            "FeiArt_Handpainted_CG_Diffusion",
            "portrait_generator_v001_ema_0.9999_1MM",
            "portrait_generator_v1.5_ema_0.9999_165000",
            "portrait_generator_v003",
            "portrait_generator_v004",
            "512x512_diffusion_uncond_entmike_ffhq_025000",
            "512x512_diffusion_uncond_entmike_ffhq_145000",
            "512x512_diffusion_uncond_entmike_ffhq_260000",
        ]:
        if mem_total > 20000:
            clip_models = [
                "ViT-B-32::openai",
                "ViT-B-16::openai",
                "RN50x64::openai",
                "ViT-L-14-336::openai"
            ]
        else:
            clip_models = [
                "ViT-B-32::openai",
                "ViT-B-16::openai",
                "ViT-L-14-336::openai"
            ]
        use_horizontal_symmetry = random.sample([True, False], 1)[0]
        w_h = random.sample([[512,512], [512,640]], 1)[0]
        cut_overview="[8]*500+[1]*500"
        cut_ic_pow="[1]*1000"
        cut_innercut="[2]*500+[2]*500"
        cut_icgray_p="[0.2]*400+[0]*600"
        

    with get_database() as client:
        job_uuid = str(job_uuid)
        record = {
            "uuid": job_uuid,
            "render_type": render_type,  # important
            "nsfw": nsfw,
            "agent_id": agent_id,
            "text_prompt": text_prompt,
            "steps": steps,
            "width_height": w_h,
            "clip_models": clip_models,
            "use_secondary_model": use_secondary_model,
            "diffusion_model": diffusion_model,
            "author": author_id,
            "status": "processing",
            "timestamp": datetime.utcnow(),
            "last_preview": datetime.utcnow(),
            "gpu_preference" : "medium",
            # defaults
            "cut_overview":cut_overview,
            "cut_innercut":cut_innercut,
            "cut_ic_pow":cut_ic_pow,
            "cut_icgray_p":cut_icgray_p,
            "skip_steps": 0,
            "init_scale":1000,
            "clip_guidance_scale": clip_guidance_scale,
            "tv_scale": 0,
            "range_scale": 150,
            "sat_scale": 0,
            "cutn_batches": 4,
            "diffusion_sampling_mode": "ddim",
            "perlin_init": False,
            "perlin_mode": "mixed",
            "eta": 0.8,
            "clamp_grad" : True,
            "clamp_max": 0.05,
            "randomize_class" : True,
            "clip_denoised" : False,
            "fuzzy_prompt" : False,
            "rand_mag" : 0.05,
            "use_vertical_symmetry": False,
            "use_horizontal_symmetry": use_horizontal_symmetry,
            "transformation_percent":[0.09],
            "skip_augs": False,
            "on_misspelled_token": "ignore",
            "text_clip_on_cpu": False,
                
                # aspect_ratio: (data.aspect_ratio !==undefined)?data.aspect_ratio:"free",
                # lock_ratio: (data.lock_ratio !==undefined)?data.lock_ratio:false



        }
        client.database.queue.insert_one(record)
        e = {"type": "progress", "agent": agent_id, "job_uuid": job_uuid, "percent": 0, "gpustats": None}
        # event(e)

    dream_job = {"message ": f"You are dreaming.  (Job '{job_uuid}')", "uuid": job_uuid, "details": json.loads(dumps(record)), "success": True}
    return dream_job






# Disco Diffusion endpoints
@app.route("/web/retry", methods=["POST"])
@requires_auth
def web_retry():
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    job_uuid = request.json.get("uuid")
    with get_database() as client:
        job = client.database.unified_jobs.find_one({"uuid": job_uuid, "author" : discord_id})
        logger.info(job)
        if not job:
            logger.info(f"❌ Retry Error: {job_uuid} not found for {discord_id}")
            return dumps({
                "message" : "Job could not be marked for retry.",
                "success" : False
            })
        else:
            algo = job.get("algo")

    if algo == "stable":
        with get_database() as client:
            client.database.stable_jobs.update_one({"uuid": job_uuid, "author" : discord_id}, {
                "$set": {
                    "user_id": discord_id,
                    "status": "queued",
                    "avoid_last_agent": True
                }
            }, upsert=True)
    else:
        with get_database() as client:
            client.database.queue.update_one({"uuid": job_uuid, "author" : discord_id}, {
                "$set": {
                    "user_id": discord_id,
                    "status": "queued",
                    "avoid_last_agent": True
                }
            }, upsert=True)
    
    return dumps({
        "message" : "Job marked for retry.",
        "success" : True
    })

@app.route("/web/cancel", methods=["POST"])
@requires_auth
def web_cancel():
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    job_uuid = request.json.get("uuid")
    with get_database() as client:
        job = client.database.unified_jobs.find_one({"uuid": job_uuid, "author" : discord_id})
        logger.info(job)
        if not job:
            logger.info(f"❌ Cancel Error: {job_uuid} not found for {discord_id}")
            return dumps({
                "message" : "Job could not be marked for cancel.",
                "success" : False
            })
        else:
            algo = job.get("algo")
    if algo == "stable":
        with get_database() as client:
            client.database.stable_jobs.delete_one({"uuid": job_uuid, "author" : discord_id})       
    else:
        with get_database() as client:
            client.database.queue.delete_one({"uuid": job_uuid, "author" : discord_id})
      
    return dumps({
        "message" : "Job cancelled.",
        "success" : True
    })

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
        # Get oldest dream
        dream = client.database.userdreams.find_one(
            {
                "$query": {
                    "version": "2.0",
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
            client.database.userdreams.update_one({"author_id": dream.get("author_id")}, {"$set": {"last_used": datetime.utcnow(), "count": count}}, upsert=True)
            return dream
        else:
            logger.info("no dream")
            return None

datetime
@app.route("/awaken/<author_id>", methods=["GET"])
def awaken(author_id):
    with get_database() as client:
        dreamCollection = client.database.get_collection("userdreams")
        # dreamCollection.delete_many({"dream": {"$exists": False}})
        dreamCollection.delete_one({"author_id": int(author_id)})
        return dumps({"message": f"Dream for {author_id} deleted."})

@app.route("/web/dream", methods=["POST", "GET"])
@requires_auth
def webdream():
    current_user = _request_ctx_stack.top.current_user
    # user_pulse(current_user)
    discord_id = current_user["sub"].split("|")[2]

    if request.method == "GET":
        with get_database() as client:
            dreamCollection = client.database.get_collection("userdreams")
            dream = dreamCollection.find_one({"author_id": int(discord_id)})
            try:
                del(dream["_id"])
            except:
                pass
            if not dream:
                dream = {
                    "prompt" : "",
                    "dream_count" : 0,
                    "diffusion_model" : "512x512_diffusion_uncond_finetune_008100"
                }
            return dumps(dream)

    if request.method == "POST":
        with get_database() as client:
            dream = request.json.get("dream")

            logger.info(dream)

            dream["author_id"] = int(discord_id)
            dream["version"] = "2.0"
            dream["is_nightmare"] = False
            dream["count"] = 0
            dream["last_used"] = datetime.utcnow()
            dream["timestamp"] = datetime.utcnow()
            client.database.userdreams.update_one(
                {"author_id": int(discord_id)},
                {
                    "$set": dream
                },
                upsert=True,
            )
            # return dumps({"success": True})
            return dumps({"success":True, "dream" : dream})


@app.errorhandler(AuthError)
def handle_auth_error(ex):
    response = jsonify(ex.error)
    response.status_code = ex.status_code
    return response

