from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ytmusicapi import YTMusic
import uvicorn
import sys
import threading
import time
import json
import os
import logging
from io import StringIO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="GiftBubble Music API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

auth_state = {"url": "", "code": "", "done": False, "error": "", "started": False}

def _init_yt():
    global yt
    try:
        if os.path.exists("oauth.json"):
            yt = YTMusic("oauth.json")
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
        import importlib
        const = importlib.import_module("ytmusicapi.constants")
        cid = getattr(const, "OAUTH_CLIENT_ID", None) or getattr(const, "YT_CLIENT_ID", None) or getattr(const, "CLIENT_ID", None)
        csec = getattr(const, "OAUTH_CLIENT_SECRET", None) or getattr(const, "YT_CLIENT_SECRET", None) or getattr(const, "CLIENT_SECRET", None)

        if not cid or not csec:
            # Try from oauth module
            oauth_mod = importlib.import_module("ytmusicapi.auth.oauth")
            cid = cid or getattr(oauth_mod, "YT_CLIENT_ID", None)
            csec = csec or getattr(oauth_mod, "YT_CLIENT_SECRET", None)

        if not cid or not csec:
            auth_state["error"] = "Could not find OAuth credentials"
            return

        import requests as req
        resp = req.post("https://oauth2.googleapis.com/device/code", data={
            "client_id": cid,
            "scope": "https://www.googleapis.com/auth/youtube"
        }, timeout=10)
        cd = resp.json()
        auth_state["url"] = cd.get("verification_url", "https://www.google.com/device")
        auth_state["code"] = cd.get("user_code", "")
        dc = cd.get("device_code", "")
        interval = cd.get("interval", 5)

        for _ in range(120):
            time.sleep(interval)
            resp = req.post("https://oauth2.googleapis.com/token", data={
                "client_id": cid, "client_secret": csec,
                "device_code": dc, "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
            }, timeout=10)
            data = resp.json()
            if resp.status_code == 200:
                with open("oauth.json", "w") as f:
                    json.dump({"access_token": data["access_token"],
                               "refresh_token": data.get("refresh_token", ""),
                               "expires_in": data.get("expires_in", 3600),
                               "scope": data.get("scope", ""),
                               "token_type": data.get("token_type", "Bearer")}, f)
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
    if not q:
        return JSONResponse(content=[], status_code=200)
    try:
        results = yt.search(q, filter="songs", limit=20)
        items = []
        for r in results:
            items.append({
                "title": r.get("title", ""),
                "videoId": r.get("videoId", ""),
                "artist": r.get("artists", [{}])[0].get("name", "") if r.get("artists") else "",
                "thumbnails": r.get("thumbnails", []),
                "duration": r.get("duration", "")
            })
        return JSONResponse(content=items, status_code=200)
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
                        "title": c.get("title", ""),
                        "videoId": c.get("videoId", ""),
                        "artist": c.get("artist", c.get("description", "")),
                        "thumbnail": c.get("thumbnails", [{}])[0].get("url", "") if c.get("thumbnails") else ""
                    })
            if items:
                sections.append({"title": title, "items": items})
        return JSONResponse(content=sections, status_code=200)
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
            "playability": playability,
            "url": url
        }, status_code=200)
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
            return JSONResponse(content={"url": "", "needAuth": True}, status_code=200)
        if not url:
            return JSONResponse(content={"url": "", "error": "No stream URL found"}, status_code=200)
        return JSONResponse(content={"url": url}, status_code=200)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/auth-url")
def auth_url():
    if auth_state["done"]:
        return JSONResponse(content={"done": True, "message": "Already authenticated"}, status_code=200)
    if not auth_state["started"]:
        auth_state["started"] = True
        thread = threading.Thread(target=_do_oauth, daemon=True)
        thread.start()
        time.sleep(1)
    return JSONResponse(content={
        "url": auth_state["url"],
        "code": auth_state["code"],
        "done": auth_state["done"],
        "error": auth_state["error"]
    }, status_code=200)

@app.get("/auth-status")
def auth_status():
    return JSONResponse(content={
        "done": auth_state["done"],
        "error": auth_state["error"]
    }, status_code=200)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
