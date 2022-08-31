import sys
from os import getenv

sys.path.append(".")
from loguru import logger
from db import get_database

# Install the API client: https://www.algolia.com/doc/api-client/getting-started/install/python/?client=python
from algoliasearch.search_client import SearchClient
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# Get your Algolia Application ID and (admin) API key from the dashboard: https://www.algolia.com/account/api-keys
# and choose a name for your index. Add these environment variables to a `.env` file:
ALGOLIA_APP_ID = getenv("ALGOLIA_APP_ID")
ALGOLIA_API_KEY = getenv("ALGOLIA_API_KEY")
ALGOLIA_INDEX_NAME = getenv("ALGOLIA_INDEX_NAME")

# Start the API client
# https://www.algolia.com/doc/api-client/getting-started/instantiate-client-index/
client = SearchClient.create(ALGOLIA_APP_ID, ALGOLIA_API_KEY)

# Create an index (or connect to it, if an index with the name `ALGOLIA_INDEX_NAME` already exists)
# https://www.algolia.com/doc/api-client/getting-started/instantiate-client-index/#initialize-an-index
index = client.init_index(ALGOLIA_INDEX_NAME)

# Add new objects to the index
# https://www.algolia.com/doc/api-reference/api-methods/add-objects/
with get_database() as db_client:
    r = db_client.database.get_collection("queue").aggregate([{"$match": {"indexed": {"$exists": False}, "status": {"$in": ["completed", "archived"]}}}])
    a = []
    for i, row in enumerate(r):
        a.append({"objectID": row.get("uuid"), "uuid": row.get("uuid"), "text_prompt": row.get("text_prompt")})
    res = index.save_objects(a)
    res.wait()
    logger.info("Done")
    for i, row in enumerate(r):
        with get_database() as client:
            # client.database.get_collection("queue").update_one({"uuid": row["uuid"]}, {"$set": {"thumbnails": [64, 128, 256, 512, 1024]}})
            client.database.get_collection("queue").update_one({"uuid": row["uuid"]}, {"$set": {"indexed": True}})

# new_object = {'objectID': 1, 'name': 'Foo'}
# Wait for the indexing task to complete
# https://www.algolia.com/doc/api-reference/api-methods/wait-task/


# Search the index for "Fo"
# https://www.algolia.com/doc/api-reference/api-methods/search/
objects = index.search("Fo")
print(objects)
