from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ytmusicapi import YTMusic, OAuthCredentials
import requests
import uvicorn
import os
import time
import json
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
            yt = YTMusic("oauth.json", clients=["android"])
            logger.info("Authenticated YTMusic (android client)")
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
        # Step 1: get device code
        r = requests.post("https://oauth2.googleapis.com/device/code", data={
            "client_id": CID, "scope": "https://www.googleapis.com/auth/youtube"
        })
        dc = r.json()
        auth_state["url"] = dc.get("verification_url", "https://www.google.com/device")
        auth_state["code"] = dc.get("user_code", "")
        device_code = dc.get("device_code", "")
        interval = dc.get("interval", 5)
        logger.info(f"OAuth URL: {auth_state['url']}, Code: {auth_state['code']}")

        # Step 2: poll until user authenticates
        for _ in range(120):
            time.sleep(interval)
            r = requests.post("https://oauth2.googleapis.com/token", data={
                "client_id": CID, "client_secret": CSEC,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
            })
            data = r.json()
            if "access_token" in data:
                with open("oauth.json", "w") as f:
                    json.dump(data, f)
                logger.info("OAuth token saved")
                auth_state["done"] = True
                _init_yt()
                return
            error = data.get("error", "")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            if error:
                auth_state["error"] = error
                logger.error(f"OAuth poll error: {error}")
                return
        auth_state["error"] = "timeout: user did not authenticate within ~10 min"
    except Exception as e:
        auth_state["error"] = str(e)[:200]
        logger.error(f"OAuth error: {e}")

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

@app.get("/stream")
def stream(videoId: str = ""):
    if not videoId:
        return JSONResponse(content={"error": "videoId required"}, status_code=400)
    try:
        data = yt.get_song(videoId)
        streaming = data.get("streamingData", {})
        if streaming:
            for f in streaming.get("adaptiveFormats", []):
                if f.get("url"):
                    return JSONResponse(content={"url": f["url"]})
            for f in streaming.get("formats", []):
                if f.get("url"):
                    return JSONResponse(content={"url": f["url"]})
    except:
        pass

    # fallback: direct YouTube player request with browser headers
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        player_url = f"https://www.youtube.com/watch?v={videoId}"
        r = requests.get(player_url, headers=headers, timeout=15)
        import re
        # extract streaming data from ytInitialPlayerResponse
        match = re.search(r'ytInitialPlayerResponse\s*=\s*({.*?});', r.text, re.DOTALL)
        if match:
            import json
            data = json.loads(match.group(1))
            streaming = data.get("streamingData", {})
            for f in streaming.get("adaptiveFormats", []):
                if f.get("url"):
                    return JSONResponse(content={"url": f["url"]})
            for f in streaming.get("formats", []):
                if f.get("url"):
                    return JSONResponse(content={"url": f["url"]})
            # check for cipher
            for f in streaming.get("adaptiveFormats", []):
                if f.get("signatureCipher"):
                    return JSONResponse(content={"cipher": f["signatureCipher"][:200]})
        return JSONResponse(content={"error": "no url found via direct request"})
    except Exception as e:
        return JSONResponse(content={"error": str(e)[:200]})

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

@app.get("/debug-oauth")
def debug_oauth():
    if os.path.exists("oauth.json"):
        with open("oauth.json") as f:
            return JSONResponse(content=json.load(f))
    return JSONResponse(content={"message": "no oauth.json"})

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
