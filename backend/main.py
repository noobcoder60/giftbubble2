from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ytmusicapi import YTMusic, setup_oauth, OAuthCredentials
import uvicorn
import os
import sys
import time
import json
import threading
import logging
from io import StringIO

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
        auth_state["url"] = ""
        auth_state["code"] = ""

        old = sys.stdout
        buf = StringIO()
        sys.stdout = buf

        try:
            setup_oauth(CID, CSEC, "oauth.json", open_browser=False)
        except EOFError:
            pass
        except Exception as e:
            logger.warning(f"setup_oauth: {e}")
        finally:
            sys.stdout = old

        out = buf.getvalue()
        for line in out.split("\n"):
            l = line.strip()
            if "http" in l.lower() and "google" in l.lower():
                auth_state["url"] = l
            if ":" in l and len(l) > 5 and len(l) < 30:
                auth_state["code"] = l.split(":")[-1].strip()

        if os.path.exists("oauth.json"):
            auth_state["done"] = True
            _init_yt()
    except Exception as e:
        auth_state["error"] = str(e)[:100]

def _wait_for_auth():
    for _ in range(120):
        time.sleep(5)
        if os.path.exists("oauth.json"):
            auth_state["done"] = True
            _init_yt()
            return

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
        return JSONResponse(content={
            "title": data.get("videoDetails", {}).get("title", ""),
            "artist": data.get("videoDetails", {}).get("author", ""),
            "thumbnail": data.get("videoDetails", {}).get("thumbnail", {}).get("thumbnails", [{}])[0].get("url", ""),
            "playability": data.get("playabilityStatus", {}).get("status", ""),
        })
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/stream")
def stream(videoId: str = ""):
    if not videoId:
        return JSONResponse(content={"error": "videoId required"}, status_code=400)
    try:
        data = yt.get_song(videoId)
        streaming = data.get("streamingData", {})
        formats = streaming.get("formats", []) + streaming.get("adaptiveFormats", [])
        url = ""
        for f in formats:
            if f.get("url"):
                url = f["url"]
                break
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
        time.sleep(3)
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
