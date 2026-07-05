from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ytmusicapi import YTMusic, OAuthCredentials
import uvicorn
import os
import time
import json
import requests
import threading
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="GiftBubble Music API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CID = "202468624474-35s5hco0taer5dqgtbu49gbuqds0gmef.apps.googleusercontent.com"
CSEC = "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"

auth_state = {"url": "", "code": "", "done": False, "error": "", "started": False}

def _init_yt():
    global yt
    try:
        if os.path.exists("oauth.json"):
            yt = YTMusic("oauth.json", oauth_credentials=OAuthCredentials(CID, CSEC))
            logger.info("Authenticated YTMusic")
            return
        yt = YTMusic()
        logger.info("Unauthenticated YTMusic")
    except Exception as e:
        logger.error(f"YT init: {e}")
        yt = YTMusic()

yt = None
_init_yt()

def _do_oauth():
    try:
        # Step 1: Get device code
        r = requests.post("https://oauth2.googleapis.com/device/code", data={
            "client_id": CID, "scope": "https://www.googleapis.com/auth/youtube"
        }, timeout=10)
        cd = r.json()
        auth_state["url"] = cd.get("verification_url", "https://www.google.com/device")
        auth_state["code"] = cd.get("user_code", "")
        dc = cd.get("device_code", "")
        interval = cd.get("interval", 5)

        # Step 2: Poll for token
        for _ in range(120):
            time.sleep(interval)
            r = requests.post("https://oauth2.googleapis.com/token", data={
                "client_id": CID, "client_secret": CSEC,
                "device_code": dc, "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
            }, timeout=10)
            data = r.json()
            if r.status_code == 200:
                token = {"access_token": data["access_token"],
                         "refresh_token": data.get("refresh_token", ""),
                         "expires_at": int(time.time()) + data.get("expires_in", 3600),
                         "expires_in": data.get("expires_in", 3600),
                         "scope": data.get("scope", ""),
                         "token_type": data.get("token_type", "Bearer")}
                with open("oauth.json", "w") as f:
                    json.dump(token, f)
                auth_state["done"] = True
                _init_yt()
                return
            if data.get("error") == "access_denied":
                auth_state["error"] = "Access denied"
                return
    except Exception as e:
        auth_state["error"] = f"{type(e).__name__}: {str(e)[:100]}"

@app.get("/search")
def search(q: str = ""):
    if not q: return JSONResponse(content=[])
    try:
        results = yt.search(q, filter="songs", limit=20)
        items = []
        for r in results:
            items.append({
                "title": r.get("title", ""), "videoId": r.get("videoId", ""),
                "artist": r.get("artists", [{}])[0].get("name", "") if r.get("artists") else "",
                "thumbnails": r.get("thumbnails", []), "duration": r.get("duration", "")
            })
        return JSONResponse(content=items)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/home")
def home():
    try:
        results = yt.get_home(limit=10)
        sections = []
        for section in results:
            title = section.get("title", "")
            contents = section.get("contents", [])
            items = []
            for c in contents:
                if c.get("videoId"):
                    items.append({
                        "title": c.get("title", ""), "videoId": c.get("videoId", ""),
                        "artist": c.get("artist", c.get("description", "")),
                        "thumbnail": c.get("thumbnails", [{}])[0].get("url", "") if c.get("thumbnails") else ""
                    })
            if items:
                sections.append({"title": title, "items": items})
        return JSONResponse(content=sections)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/song")
def song(videoId: str = ""):
    if not videoId:
        return JSONResponse(content={"error": "videoId required"}, status_code=400)
    try:
        data = yt.get_song(videoId)
        playability = data.get("playabilityStatus", {}).get("status", "")
        streaming = data.get("streamingData", {})
        formats = streaming.get("formats", []) + streaming.get("adaptiveFormats", [])
        url = ""
        for f in formats:
            if f.get("url"):
                url = f["url"]
                break
        return JSONResponse(content={
            "title": data.get("videoDetails", {}).get("title", ""),
            "artist": data.get("videoDetails", {}).get("author", ""),
            "thumbnail": data.get("videoDetails", {}).get("thumbnail", {}).get("thumbnails", [{}])[0].get("url", ""),
            "playability": playability, "url": url
        })
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/stream")
def stream(videoId: str = ""):
    if not videoId:
        return JSONResponse(content={"error": "videoId required"}, status_code=400)
    try:
        data = yt.get_song(videoId)
        playability = data.get("playabilityStatus", {}).get("status", "")
        streaming = data.get("streamingData", {})
        formats = streaming.get("formats", []) + streaming.get("adaptiveFormats", [])
        url = ""
        for f in formats:
            if f.get("url"):
                url = f["url"]
                break
        if not url and playability == "LOGIN_REQUIRED":
            return JSONResponse(content={"url": "", "needAuth": True})
        if not url:
            return JSONResponse(content={"url": "", "error": "No stream URL found"})
        return JSONResponse(content={"url": url})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/auth-url")
def auth_url():
    if auth_state["done"]:
        return JSONResponse(content={"done": True})
    if not auth_state["started"]:
        auth_state["started"] = True
        thread = threading.Thread(target=_do_oauth, daemon=True)
        thread.start()
        time.sleep(2)
    return JSONResponse(content={
        "url": auth_state["url"], "code": auth_state["code"],
        "done": auth_state["done"], "error": auth_state["error"]
    })

@app.get("/auth-status")
def auth_status():
    return JSONResponse(content={"done": auth_state["done"], "error": auth_state["error"]})

@app.get("/reset-auth")
def reset_auth():
    if os.path.exists("oauth.json"):
        os.remove("oauth.json")
    auth_state["started"] = False
    auth_state["done"] = False
    auth_state["url"] = ""
    auth_state["code"] = ""
    auth_state["error"] = ""
    _init_yt()
    return JSONResponse(content={"message": "reset"})

@app.get("/debug")
def debug():
    info = {"has_oauth": os.path.exists("oauth.json"), "yt_initialized": yt is not None}
    if os.path.exists("oauth.json"):
        with open("oauth.json") as f:
            info["token_keys"] = list(json.load(f).keys())
    return JSONResponse(content=info)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
