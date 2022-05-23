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

# https://iq-inc.com/wp-content/uploads/2021/02/AndyRelativeImports-300x294.jpg
sys.path.append(".")
from db import get_database

# load_dotenv()

UPLOAD_FOLDER = "images"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def log(message):
    with get_database() as client:
        logTable = client.database.get_collection("log")
        logTable.insert_one({"timestamp": datetime.now(), "message": message, "ack": False})


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
            log(f"A new agent has joined! 😍 Thank you, {agent_id}!")
        else:
            status = f"😓 Sorry, someone already registered an agent by that name.  Try another one!"
    return status


@app.route("/upload/<agent_id>/<job_uuid>", methods=["GET", "POST"])
def upload_file(agent_id, job_uuid):
    if request.method == "POST":
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
                results = queueCollection.update_one({"agent_id": agent_id, "uuid": job_uuid}, {"$set": {"status": "complete", "filename": filename}})
                count = results.modified_count
            if count == 0:
                return f"cannot find that job."
            else:
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


@app.route("/takeorder/<agent_id>")
def takeorder(agent_id):
    with get_database() as client:
        queueCollection = client.database.get_collection("queue")
        query = {"status": "processing", "agent_id": agent_id}
        jobCount = queueCollection.count_documents(query)
        if jobCount > 0:
            jobs = queueCollection.find_one(query)
            return dumps({"message ": f"You already have a job.  (Job '{jobs.get('uuid')}')", "uuid": jobs.get("uuid"), "success": True})
        else:
            query = {"status": "queued"}
            queueCount = queueCollection.count_documents(query)
            if queueCount > 0:
                job_uuid = queueCollection.find_one({"$query": query, "$orderby": {"timestamp": 1}})["uuid"]
                results = queueCollection.update_one({"uuid": job_uuid}, {"$set": {"status": "processing", "agent_id": agent_id}})
                count = results.modified_count
                if count > 0:
                    return dumps({"message": f"Your current job is {job_uuid}.", "uuid": jobs.get("uuid"), "success": True})
                else:
                    return dumps({"message": f"Could not secure a job.", "success": False})

    return dumps({"message": f"No queued jobs at this time.", "success": False})


@app.route("/queue")
def q():
    with open("queue.yaml", "r") as queue:
        arr = full_load(queue)
    return str(arr)
