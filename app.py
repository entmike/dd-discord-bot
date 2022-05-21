import os
from flask import Flask, flash, request, redirect, url_for
from dotenv import load_dotenv
from yaml import dump, full_load
from werkzeug.utils import secure_filename
import hashlib
from datetime import datetime

# load_dotenv()

UPLOAD_FOLDER = "images"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/register/<agent_id>")
def register(agent_id):
    try:
        with open("agents.yaml", "r") as queue:
            arr = full_load(queue)
    except:
        arr = []
    found = False
    for agent in arr:
        if agent["agent_id"] == agent_id:
            found = True

    if not found:
        salt = "SaltyBoi"
        token = hashlib.sha256(f"{agent_id}{salt}".encode("utf-8")).hexdigest()
        arr.append({"agent_id": agent_id, "last_seen": datetime.now()})
        dump(arr, open("agents.yaml", "w"))
        return f"✅ Registered!  Your API token is '{token}'.  Save this, you won't see it again."
    else:
        return f"😓 Sorry, someone already registered an agent by that name.  Try another one!"


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
            flash("No selected file")
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            found = False
            with open("queue.yaml", "r") as queue:
                arr = full_load(queue)
                for job in arr:
                    if job["uuid"] == job_uuid:
                        found = True
                        job["status"] = "complete"
                        job["filename"] = filename
                if found:
                    dump(arr, open("queue.yaml", "w"))
                    return f"thank you, {agent_id}."
                else:
                    return f"cannot find that job."
            # return redirect(url_for('download_file', name=filename))
    else:
        return """
        <!doctype html>
        <title>Upload new File</title>
        <h1>Upload new File</h1>
        <form method=post enctype=multipart/form-data>
        <input type=file name=file>
        <input type=submit value=Upload>
        </form>
        """


@app.route("/")
def hello_world():
    return "<p>Hello, World!</p>"


@app.route("/takeorder/<agent_id>")
def takeorder(agent_id):
    with open("queue.yaml", "r") as queue:
        arr = full_load(queue)
    if (len(arr)) > 0:
        job = arr[0]
        job["status"] = "processing"
        job["agent"] = agent_id
        dump(arr, open("queue.yaml", "w"))
        return str(job)
    else:
        return str({})


@app.route("/queue")
def q():
    with open("queue.yaml", "r") as queue:
        arr = full_load(queue)
    return str(arr)
