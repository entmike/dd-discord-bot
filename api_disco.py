# Disco Diffusion endpoints
@app.route("/web/retry", methods=["POST"])
@requires_auth
def web_retry():
    current_user = _request_ctx_stack.top.current_user
    discord_id = int(current_user["sub"].split("|")[2])
    job_uuid = request.json.get("uuid")
    logger.info(job)
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
    logger.info(job)
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