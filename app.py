import os, sys
from webbrowser import get
from flask import Flask, flash, request, redirect, url_for
from dotenv import load_dotenv
from yaml import dump, full_load
from werkzeug.utils import secure_filename
import hashlib
from datetime import datetime
from bson import Binary, Code
from bson.json_util import dumps
import uuid
import json
from loguru import logger

# https://iq-inc.com/wp-content/uploads/2021/02/AndyRelativeImports-300x294.jpg
sys.path.append(".")
from db import get_database

# load_dotenv()

UPLOAD_FOLDER = "images"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "log"}

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def log(message, title="Message"):
    with get_database() as client:
        logTable = client.database.get_collection("logs")
        logTable.insert_one({"timestamp": datetime.now(), "message": message, "title": title, "ack": False, "uuid": str(uuid.uuid4())})

def event(event):
    with get_database() as client:
        eventTable = client.database.get_collection("events")
        eventTable.insert_one({"timestamp": datetime.now(), "ack": False, "uuid": str(uuid.uuid4()), "event" : event})
    logger.info(f"Event logged: {event}")

# @app.route("/job/<job_uuid>")
# def job(job_uuid):

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
            salt = "SaltyBoi"
            token = hashlib.sha256(f"{agent_id}{salt}".encode("utf-8")).hexdigest()
            agentCollection.insert_one({"agent_id": agent_id, "last_seen": datetime.now()})
            status = f"✅ Registered!  Your API token is '{token}'.  Save this, you won't see it again."
            log(f"A new agent has joined! 😍 Thank you, {agent_id}!", title="🆕 New Agent")
        else:
            status = f"😓 Sorry, someone already registered an agent by that name.  Try another one!"
    return status

def pulse(agent_id):
    with get_database() as client:
        agentCollection = client.database.get_collection("agents")
        agentCollection.update_one({"agent_id": agent_id},
        {"$set": {"last_seen": datetime.now()}})

@app.route("/reject/<agent_id>/<job_uuid>", methods=["POST"])
def reject(agent_id, job_uuid):
    pulse(agent_id=agent_id)
    logger.error(f"rejecting {job_uuid}")
    if request.method == "POST":
        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            results = queueCollection.update_one({
                "agent_id": agent_id, 
                "uuid": job_uuid}, {"$set": {"status": "failed", "filename": None}})
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
        results = queueCollection.update_one({
            "agent_id": agent_id, 
            "uuid": job_uuid}, {"$set": {"log": filename}})
        count = results.modified_count
        if count == 0:
            return f"cannot find that job."
        else:
            return "Log uploaded."

@app.route("/progress/<agent_id>/<job_uuid>", methods=["GET", "POST"])
def progress(agent_id, job_uuid):
    if request.method == "POST":
        e = {
            "type" : "progress",
            "agent" : agent_id,
            "job_uuid" : job_uuid,
            "percent" : request.form.get('percent')
        }
        event(e)
        # logger.info(e)

        with get_database() as client:
            queueCollection = client.database.get_collection("queue")
            results = queueCollection.update_one({
                "agent_id": agent_id, 
                "uuid": job_uuid}, {"$set": {"percent": request.form.get('percent')}})
            count = results.modified_count
            if count == 0:
                return f"cannot find that job."
            else:
                return "Log uploaded."
        
    if request.method == "GET":
        return "OK"

@app.route("/upload/<agent_id>/<job_uuid>", methods=["GET", "POST"])
def upload_file(agent_id, job_uuid):
    pulse(agent_id=agent_id)
    if request.method == "POST":
        logger.info(request.form.get('duration'))
        if request.form.get('duration'):
            duration = float(request.form.get('duration'))
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
                results = queueCollection.update_one({
                    "agent_id": agent_id, 
                    "uuid": job_uuid}, {"$set": {"status": "complete", "filename": filename, "duration":duration}})
                count = results.modified_count
            if count == 0:
                return f"cannot find that job."
            else:
                with get_database() as client:
                    agentCollection = client.database.get_collection("agents")
                    results = agentCollection.find_one({"agent_id" : agent_id})
                    score = results.get("score")
                    if not score:
                        score = 1
                    else:
                        score+=1
                    results = agentCollection.update_one({
                        "agent_id": agent_id}, {"$set": {"score": score}})
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
def hello_world():
    return "<p>Hello, World!</p>"

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

@app.route("/takeorder/<agent_id>/<idle_time>")
def takeorder(agent_id, idle_time):
    pulse(agent_id=agent_id)
    mode = "awake"
    if int(idle_time) > 30:
        mode = "dreaming"
    else:
        mode = "awake"
    with get_database() as client:
            agentCollection = client.database.get_collection("agents")
            agentCollection.update_one({"agent_id": agent_id}, {"$set": {"mode": mode}})
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
            return dumps({"message ": f"You already have a job.  (Job '{jobs.get('uuid')}')", 
                "uuid": jobs.get("uuid"), 
                "details":json.loads(dumps(jobs)),
                "success": True
            })
        else:
            # Check for sketches first
            query = {"status": "queued", "render_type": "sketch"}
            queueCount = queueCollection.count_documents(query)           
            if queueCount == 0:
                query = {"status": "queued", "render_type": None}
                queueCount = queueCollection.count_documents(query)

            if queueCount > 0:
                # Work found
                job = queueCollection.find_one({"$query": query, "$orderby": {"timestamp": 1}})
                results = queueCollection.update_one({"uuid": job.get("uuid")}, {"$set": {"status": "processing", "agent_id": agent_id}})
                count = results.modified_count
                if count > 0:
                    log(f"Good news, <@{job.get('author')}>!  Your job `{job.get('uuid')}` is being processed now by `{agent_id}`...", title="💼 Job in Process")
                    agentCollection = client.database.get_collection("agents")
                    agentCollection.update_one({"agent_id": agent_id}, {"$set": {"mode": "working", "idle_time":0}})
                    return dumps({"message": f"Your current job is {job.get('uuid')}.", "uuid": job.get("uuid"), "details":json.loads(dumps(job)), "success": True})
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
    templates = [
        "a highly detailed {adjectives} nebula with majestic planets of {of_something}, art by {progrock/artist}, trending on artstation",
        "a beautiful watercolor painting of a {adjectives} {animals} in {locations}, art by {artists}, trending on artstation",
        "an ominous sculpture of {animals}s in the shape of {shapes} made of {of_something}, digital painting",
        "a horrible {adjectives} {adjectives} fuzzy {locations} soaked in {things}, art by {artists}",
        "a colorful galactic {locations} colored {colors}, art by {artists}",
        "a {things} sinking in a {locations} covered in {things}s, watercolor, trending on artstation",
        "an immaculately detailed gothic painting of a {things} surrounded by majestic {things}, art by {artists}, {styles} style",
        # "{progrock/adjective} ophanim, tarot card, {progrock/style}",
        # "a {progrock/adjective} photo of a {locations} taken by {progrock/artist}, UHD, photorealistic",
        "a verdant overgrown {locations}, {progrock/style}",
        "{progrock/adjective} {colors} {shapes}s, vector art by {progrock/artist}",
        "A beautiful landscape on an alien planet with giant {things}s, and {adjectives} vegetation Giant {colors} and {things} in the {locations} by {artists}, greg rutkowski, {artists}, {artists}, {artists} Trending on artstation and SF ART"
        # "The {colors} of the {locations} is a representation of the Viking's obsession with the {locations}",
        # "The Korean girl is doing a {progrock/adjective} {progrock/style} painting in the digital age",
        # "The face of the {animals} is now etched in the {progrock/style} art of Japan",
        # "The Veiled Virgin Statue by {progrock/artist} covered in {progrock/adjective} cellophane centered in a {locations}",
        # "{progrock/adjective} {animals} crystal"
    ]
    import random
    template = random.sample(templates,1)[0]
    shape = random.sample([
        "square", "pano", "landscape","portrait"
    ],1)[0]
    model = random.sample([
        "default", "rn50x64", "vitl14","vitl14x336"
    ],1)[0]
    steps = random.sample([
        150, 200, 250, 300, 400
    ],1)[0]
    cut_ic_pow = random.sample([
        1, 5, 10, 20, 50, 100
    ],1)[0]
    clip_guidance_scale = random.sample([
        5000, 7500, 10000, 15000, 20000
    ],1)[0]
    sat_scale = random.sample([
        0, 100, 500, 1000, 5000, 10000, 20000
    ],1)[0]
    with get_database() as client:
        job_uuid = str(job_uuid)
        salad = dd_prompt_salad.make_random_prompt(amount=1, prompt_salad_path="prompt_salad", template=template)[0]
        text_prompt = salad
        record = {
            "uuid": job_uuid, 
            "mode": "dream",    # important
            "agent_id": agent_id,
            "text_prompt": text_prompt, 
            "steps": steps, 
            "shape": shape, 
            "model": model,
            "clip_guidance_scale": clip_guidance_scale,
            "clamp_max" : 0.05,
            "cut_ic_pow": cut_ic_pow,
            "sat_scale": sat_scale,
            "author": 977198605221912616,
            "status": "processing",
            "timestamp": datetime.utcnow()}
        queueCollection = client.database.get_collection("queue")
        queueCollection.insert_one(record)

    dream_job = {"message ": f"You are dreaming.  (Job '{job_uuid}')", 
        "uuid": job_uuid, 
        "details":json.loads(dumps(record)),
        "success": True
    }
    return dream_job
