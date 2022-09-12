from functools import wraps
from flask import request
from jose import jwt
from six.moves.urllib.request import urlopen
from loguru import logger
import json
from bson.json_util import dumps
from json import loads
from flask import _request_ctx_stack
from datetime import datetime

import http.client
import os, sys
import urllib.parse

sys.path.append(".")
from db import get_database

AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN")
AUTH0_API_AUDIENCE = os.getenv("AUTH0_API_AUDIENCE")
AUTH0_ALGORITHMS = ["RS256"]
AUTH0_MGMT_API_CLIENT_ID=os.getenv("AUTH0_MGMT_API_CLIENT_ID")
AUTH0_MGMT_API_SECRET=os.getenv("AUTH0_MGMT_API_SECRET")

usercache = {}

def requires_auth(f):
    """Determines if the Access Token is valid"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_auth_header()
        jsonurl = urlopen("https://" + AUTH0_DOMAIN + "/.well-known/jwks.json")
        jwks = json.loads(jsonurl.read())
        unverified_header = jwt.get_unverified_header(token)
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {"kty": key["kty"], "kid": key["kid"], "use": key["use"], "n": key["n"], "e": key["e"]}
        if rsa_key:
            try:
                payload = jwt.decode(token, rsa_key, algorithms=AUTH0_ALGORITHMS, audience=AUTH0_API_AUDIENCE, issuer="https://" + AUTH0_DOMAIN + "/")
            except jwt.ExpiredSignatureError:
                raise AuthError({"code": "token_expired", "description": "token is expired"}, 401)
            except jwt.JWTClaimsError:
                raise AuthError({"code": "invalid_claims", "description": "incorrect claims, please check the audience and issuer"}, 401)
            except Exception:
                raise AuthError({"code": "invalid_header", "description": "Unable to parse authentication token."}, 401)

            _request_ctx_stack.top.current_user = payload
            user_info = user_pulse(payload, True)
            _request_ctx_stack.top.user_info = user_info
            logger.info(f"👤 {user_info}")

            return f(*args, **kwargs)
        raise AuthError({"code": "invalid_header", "description": "Unable to find appropriate key"}, 401)

    return decorated

def supports_auth(f):
    """Determines if the Access Token is valid"""
    @wraps(f)
    def decorated(*args, **kwargs):
        jsonurl = urlopen("https://" + AUTH0_DOMAIN + "/.well-known/jwks.json")
        jwks = json.loads(jsonurl.read())
        _request_ctx_stack.top.current_user = None
        _request_ctx_stack.top.user_info = None
        try:
            token = get_token_auth_header()
            logger.info(token)
            unverified_header = jwt.get_unverified_header(token)            
        except:
            logger.info(f"👤 Unauthenticated request, allowing.")
            return f(*args, **kwargs)

        rsa_key = {}
        user_info = None
        for key in jwks["keys"]:
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {"kty": key["kty"], "kid": key["kid"], "use": key["use"], "n": key["n"], "e": key["e"]}
        if rsa_key:
            try:
                payload = jwt.decode(token, rsa_key, algorithms=AUTH0_ALGORITHMS, audience=AUTH0_API_AUDIENCE, issuer="https://" + AUTH0_DOMAIN + "/")
                _request_ctx_stack.top.current_user = payload
                user_info = user_pulse(payload, True)
                _request_ctx_stack.top.user_info = user_info
            except jwt.ExpiredSignatureError:
                pass
                # raise AuthError({"code": "token_expired", "description": "token is expired"}, 401)
            except jwt.JWTClaimsError:
                pass
                # raise AuthError({"code": "invalid_claims", "description": "incorrect claims, please check the audience and issuer"}, 401)
            except Exception:
                pass
                # raise AuthError({"code": "invalid_header", "description": "Unable to parse authentication token."}, 401)

        logger.info(f"👤 {user_info}")
        return f(*args, **kwargs)

        # raise AuthError({"code": "invalid_header", "description": "Unable to find appropriate key"}, 401)
    return decorated

# Error handler
class AuthError(Exception):
    def __init__(self, error, status_code):
        self.error = error
        self.status_code = status_code

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
    return token

def get_auth0_mgmt_token():
    conn = http.client.HTTPSConnection("dev-yqzsn326.auth0.com")
    payload = dumps({
        "client_id":AUTH0_MGMT_API_CLIENT_ID,
        "client_secret":AUTH0_MGMT_API_SECRET,
        "audience":"https://dev-yqzsn326.auth0.com/api/v2/",
        "grant_type":"client_credentials"
    })
    headers = { 'content-type': "application/json" }
    conn.request("POST", "/oauth/token", payload, headers)
    res = conn.getresponse()
    data = res.read()

    return loads(data.decode("utf-8"))

def user_pulse(current_user, update_db):
    # logger.info(f"💓 User activity from {current_user}")
    access_token = get_auth0_mgmt_token()["access_token"]
    try:
        if usercache[access_token]:
            user_info = usercache[access_token]
    except:
        try:
            path = f"/api/v2/users/{urllib.parse.quote(current_user['sub'])}"
            conn = http.client.HTTPSConnection("dev-yqzsn326.auth0.com")
            conn.request("GET", path, headers={
                'authorization': f"Bearer {access_token}"
            })
            res = conn.getresponse()
            data = res.read()
            user_info=loads(data.decode("utf-8"))
            usercache["access_token"] = user_info
        except:
            import traceback
            tb = traceback.format_exc()
            user_info={}
            logger.error(tb)
            usercache["access_token"] = None

    discord_id = int(current_user["sub"].split("|")[2])

    # logger.info(f"📅 Updating user")
    with get_database() as client:
        client.database.users.update_one({
            "user_id": discord_id
        }, {
            "$set": {
                "last_seen": datetime.utcnow(),
                "nickname": user_info["nickname"],
                "picture": user_info["picture"]
            }
        },
        upsert=True)

    return user_info