import os
def get_database():
    from pymongo import MongoClient
    import pymongo

    # Provide the mongodb atlas url to connect python to mongodb using pymongo
    MONGODB_CONNECTION = MAX_DREAM_OCCURENCE = os.getenv('MONGODB_CONNECTION', "mongodb://mongodb/discobot")

    # Create a connection using MongoClient. You can import MongoClient or use pymongo.MongoClient
    from pymongo import MongoClient

    client = MongoClient(MONGODB_CONNECTION)
    return client


# This is added so that many files can reuse the function get_database()
if __name__ == "__main__":

    # Get the database
    dbname = get_database()
