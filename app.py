from io import BytesIO, StringIO
import jsbeautifier
import os, sys
from webbrowser import get
from flask import Flask, flash, request, redirect, url_for, jsonify, send_file
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

# https://iq-inc.com/wp-content/uploads/2021/02/AndyRelativeImports-300x294.jpg
sys.path.append(".")
from db import get_database

load_dotenv()

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "log"}
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_SALT = os.getenv("BOT_SALT")
BOT_WEBSITE = os.getenv("BOT_WEBSITE")
MAX_DREAM_OCCURENCE = os.getenv("MAX_DREAM_OCCURENCE")

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


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
    with get_database() as client:
        eventTable = client.database.get_collection("events")
        eventTable.insert_one({"timestamp": str(datetime.now()), "ack": False, "uuid": str(uuid.uuid4()), "event": event})
    # logger.info(f"Event logged: {event}")


@app.route("/toggle_pin/<user_id>/<uuid>/")
def toggle_pin(user_id, uuid):
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    logger.info("pin")
    with get_database() as client:
        pin = client.database.get_collection("pins").find_one({"uuid": uuid, "user": user_id})
        if pin:
            client.database.get_collection("pins").delete_one({"uuid": uuid, "user": user_id})
            return dumps({"message": "Unpinned"})
        else:
            client.database.get_collection("pins").insert_one({"uuid": uuid, "user": user_id})
            return dumps({"message": "Pinned"})


def pulse(agent_id):
    with get_database() as client:
        agentCollection = client.database.get_collection("agents")
        agentCollection.update_one({"agent_id": agent_id}, {"$set": {"last_seen": datetime.now()}})


def user_pulse(author_id):
    with get_database() as client:
        agentCollection = client.database.get_collection("users")
        agentCollection.update_one({"user_id": author_id}, {"$set": {"last_seen": datetime.now()}}, upsert=True)


@app.route("/random/<amount>")
def random_images(amount):
    with get_database() as client:
        r = client.database.get_collection("queue").aggregate([{"$match": {"status": "archived"}}, {"$sample": {"size": int(amount)}}])
        return dumps(r)


@app.route("/recent/<amount>")
def recent_images(amount):
    with get_database() as client:
        r = client.database.get_collection("queue").find({"$query": {"status": "archived"}, "$orderby": {"timestamp": -1}}).limit(int(amount))
        return dumps(r)


@app.route("/getsince/<seconds>", methods=["GET"])
def getsince(seconds):
    since = datetime.now() - timedelta(seconds=int(seconds))
    q = {"status": "archived", "last_preview": {"$gt": since}}
    with get_database() as client:
        query = {"$query": q, "$orderby": {"timestamp": -1}}
        queue = client.database.get_collection("queue").find(query)
        return dumps(queue)


@app.route("/queue/", methods=["GET"], defaults={"status": "all"})
@app.route("/queue/<status>/")
def queue(status):
    logger.info(f"Queue request for status {status}...")
    if status == "stalled":
        since = datetime.now() - timedelta(minutes=30)
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
        queue = client.database.get_collection("queue").find(query)
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


@app.route("/dream", methods=["POST"])
def dream():
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
                    "last_used": datetime.now(),
                    "timestamp": datetime.now(),
                }
            },
            upsert=True,
        )

    logger.info(request.form.get("dream"))
    return dumps({"message": "received"})


@app.route("/users")
def users():
    with get_database() as client:
        userCollection = client.database.get_collection("users")
        users = userCollection.find({})
        logger.info(users)
        return dumps(users)


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
                }
            },
            upsert=True,
        )
    return dumps({"success": True})


@app.route("/updatejob", methods=["POST"])
def updatejob():
    if request.headers.get("x-dd-bot-token") != BOT_TOKEN:
        return jsonify({"message": "ERROR: Unauthorized"}), 401
    uuid = request.form.get("uuid")
    logger.info(f"Updating job '{uuid}'")
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
        queueCollection = client.database.get_collection("queue")
        job = queueCollection.find_one({"uuid": job_uuid})
        opts = jsbeautifier.default_options()
        opts.indent_size = 2
        return jsonify(json.loads(dumps(job)))


@app.route("/rejects", methods=["GET"])
def rejects():
    with get_database() as client:
        queue = client.database.get_collection("queue").find({"$query": {"status": "rejected"}, "$orderby": {"timestamp": -1}})
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
        queueCollection = client.database.get_collection("queue")
        jobs = queueCollection.find(q)
        return jsonify(json.loads(dumps(jobs)))


@app.route("/job/<job_uuid>", methods=["GET", "DELETE"])
def job(job_uuid):
    if request.method == "GET":
        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            job = queueCollection.find_one({"uuid": job_uuid})
            return dumps(job)
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
def agentstats():
    with get_database() as client:
        since = datetime.now() - timedelta(minutes=10)
        agents = client.database.get_collection("agents").find({"last_seen": {"$gt": since}}).sort("last_seen", -1)
        return dumps(agents)


@app.route("/queuestats")
def queuestats():
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        queuedCount = queueCollection.count_documents({"status": "queued"})
        processingCount = queueCollection.count_documents({"status": "processing"})
        renderedCount = queueCollection.count_documents({"status": "archived"})
        rejectedCount = queueCollection.count_documents({"status": "rejected"})
        return dumps({"queuedCount": queuedCount, "processingCount": processingCount, "renderedCount": renderedCount, "rejectedCount": rejectedCount})


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


@app.route("/thumbnail/<job_uuid>", methods=["GET"], defaults={"size": 128})
@app.route("/thumbnail/<job_uuid>/<size>", methods=["GET"])
def thumbnail(job_uuid, size):
    try:
        filename = f"{job_uuid}0_0.png"
        fn = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        img = Image.open(fn)
        img.thumbnail((int(size), int(size)), Image.ANTIALIAS)
        return serve_pil_image(img)
    except Exception as e:
        return f"Could not locate {filename}.  This might be because the render has not completed yet.  Or because the job failed.  Or check your job uuid.  Or a gremlin ate the image.  Probably the gremlin.\n{e}"


@app.route("/image/<job_uuid>", methods=["GET"])
def image(job_uuid):
    try:
        filename = f"{job_uuid}0_0.png"
        fn = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        from os.path import exists

        if not exists(fn):
            filename = f"{job_uuid}_progress.png"
            fn = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        return send_file(fn, mimetype="image/png")
    except:
        return f"Could not locate {filename}.  This might be because the render has not completed yet.  Or because the job failed.  Or check your job uuid.  Or a gremlin ate the image.  Probably the gremlin."


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
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
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
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    with open(os.path.join(app.config["UPLOAD_FOLDER"], filename), "r") as f:
        run_log = f.read()

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
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], f"{job_uuid}_{filename}"))
            logger.info(f"{job_uuid}_{filename} saved.")
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
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
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


@app.route("/search/<regexp>", methods=["GET"])
def search(regexp):
    with get_database() as client:
        j = client.database.get_collection("queue").find({"text_prompt": {"$regex": regexp, "$options": "i"}})
        return dumps(j)


@app.route("/takeorder/<agent_id>", methods=["POST"])
def takeorder(agent_id):
    if request.method == "POST":
        idle_time = request.form.get("idle_time")
        model = request.form.get("model")
        pulse(agent_id=agent_id)
        mode = "awake"
        if int(idle_time) > 30:
            mode = "dreaming"
        else:
            mode = "awake"
        with get_database() as client:
            agentCollection = client.database.get_collection("agents")
            agentCollection.update_one({"agent_id": agent_id}, {"$set": {"mode": mode, "model_mode": model}})
            logger.info(f"{agent_id} is {mode}...")
        with get_database() as client:
            agentCollection = client.database.get_collection("agents")
            agentCollection.update_one({"agent_id": agent_id}, {"$set": {"idle_time": int(idle_time)}})
        logger.info(f"{agent_id} looking for work, idle time {idle_time} seconds...")
        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            query = {"status": "processing", "agent_id": agent_id}
            jobCount = queueCollection.count_documents(query)
            if jobCount > 0:
                # Update status
                agentCollection = client.database.get_collection("agents")
                agentCollection.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time": 0}})
                jobs = queueCollection.find_one(query)
                logger.info("working")
                return dumps({"message ": f"You already have a job.  (Job '{jobs.get('uuid')}')", "uuid": jobs.get("uuid"), "details": json.loads(dumps(jobs)), "success": True})
            else:
                # Check for sketches first
                query = {"status": "queued", "render_type": "sketch", "model": model}
                queueCount = queueCollection.count_documents(query)
                logger.info(f"{queueCount} sketches in queue.")
                if queueCount == 0:
                    query = {"status": "queued", "model": model}
                    queueCount = queueCollection.count_documents(query)
                    logger.info(f"{queueCount} renders in queue.")

                if queueCount > 0:
                    # Work found
                    job = queueCollection.find_one({"$query": query, "$orderby": {"timestamp": 1}})
                    results = queueCollection.update_one({"uuid": job.get("uuid")}, {"$set": {"status": "processing", "agent_id": agent_id}})
                    count = results.modified_count
                    if count > 0:
                        log(f"Good news, <@{job.get('author')}>!  Your job `{job.get('uuid')}` is being processed now by `{agent_id}`...", title="💼 Job in Process")
                        agentCollection = client.database.get_collection("agents")
                        agentCollection.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time": 0}})
                        return dumps({"message": f"Your current job is {job.get('uuid')}.", "uuid": job.get("uuid"), "details": json.loads(dumps(job)), "success": True})
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
            "render_type": "dream",  # important
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
            # "author": 977198605221912616,
            "author": author_id,
            "status": "processing",
            "timestamp": datetime.utcnow(),
        }
        queueCollection = client.database.get_collection("queue")
        queueCollection.insert_one(record)

    dream_job = {"message ": f"You are dreaming.  (Job '{job_uuid}')", "uuid": job_uuid, "details": json.loads(dumps(record)), "success": True}
    return dream_job


# @bot.slash_command(name="refresh_all", description="Refresh all images (temporary utility command)")
# async def refresh_all(ctx):
#     await ctx.respond("Acknowledged.", ephemeral=True)
#     with get_database() as client:
#         queueCollection = client.database.get_collection("queue")
#         jobs = queueCollection.find({})
#         max = 10000000
#         m = 0
#         for job in jobs:
#             if(job.get('progress_msg')):
#                 m += 1
#                 if m < max:
#                     do_refresh(job.get('uuid'))
#                 else:
#                     logger.info(f"{job.get('uuid')} max update reached...")
#             else:
#                 logger.info("no")
