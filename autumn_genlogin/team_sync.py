"""Optional self-hosted encrypted metadata sync with team access controls.

No cookies, passwords, tokens, extension binaries or browser data are synced.
The server stores opaque AES-GCM ciphertext; a passphrase stays on clients.
Server defaults to loopback; place behind a TLS reverse proxy for remote use.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

FORMAT = "AutumnGenLogin/encrypted-1"
MAX_DOCUMENT = 1024 * 1024
ROLE_LEVEL = {"viewer":0, "editor":1,"admin":2,"owner":3}


def _b64(v:bytes) -> str:
    return base64.b64encode(v).decode("ascii")


def _unb64(v:str) -> bytes:
    if not isinstance(v,str) or len(v) > MAX_DOCUMENT*2: raise ValueError("Invalid encoded data")
    return base64.b64decode(v,validate=True)


def encrypt_document(data: dict, passphrase: str) -> dict:
    """Encrypt authenticated JSON; the passphrase is not sent to the server."""
    if not isinstance(passphrase,str) or len(passphrase) < 12:
        raise ValueError("Sync passphrase needs at least 12 characters")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    key = hashlib.scrypt(passphrase.encode(),salt=salt,n=2**14,r=8,p=1,dklen=32)
    raw = json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    if len(raw) > MAX_DOCUMENT//2: raise ValueError("Sync document too large")
    return {"format":FORMAT,"salt":_b64(salt),"nonce":_b64(nonce),
            "ciphertext":_b64(AESGCM(key).encrypt(nonce, raw, FORMAT.encode()))}


def decrypt_document(blob: dict, passphrase: str) -> dict:
    if not isinstance(blob,dict) or set(blob)!={"format","salt","nonce","ciphertext"} or blob.get("format")!=FORMAT:
        raise ValueError("Invalid encrypted document")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt,nonce,encrypted=(_unb64(blob[k]) for k in ("salt","nonce","ciphertext"))
    if len(salt)!=16 or len(nonce)!=12: raise ValueError("Invalid encryption parameters")
    key=hashlib.scrypt(passphrase.encode(),salt=salt,n=2**14,r=8,p=1,dklen=32)
    plaintext=AESGCM(key).decrypt(nonce,encrypted,FORMAT.encode())
    doc=json.loads(plaintext)
    if not isinstance(doc,dict): raise ValueError("Invalid document")
    return doc


def safe_profile_metadata(store) -> dict:
    """Explicit allowlist; never export proxy endpoints, credentials or sessions."""
    keys=("id","name","group_name","tags","browser","start_url","locale","timezone_id",
          "viewport_width","viewport_height")
    return {"format":"AutumnGenLogin/profile-metadata-1",
            "profiles":[{k:getattr(p,k) for k in keys} for p in store.all()]}


class HubError(Exception):
    def __init__(self,status:int,message:str):
        self.status,self.message=status,message
        super().__init__(message)


class TeamHub:
    """Identity, roles, per-team documents and optimistic revisions."""
    def __init__(self,db_path:Path):
        self.db_path=Path(db_path)
        self.db_path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self._db()) as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE,
                    salt BLOB NOT NULL,password_hash BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,
                    expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY,name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS members(team_id TEXT NOT NULL,user_id TEXT NOT NULL,
                    role TEXT NOT NULL,PRIMARY KEY(team_id,user_id));
                CREATE TABLE IF NOT EXISTS documents(team_id TEXT NOT NULL,name TEXT NOT NULL,
                    revision INTEGER NOT NULL,blob TEXT NOT NULL,PRIMARY KEY(team_id,name));
            """)

    def _db(self):
        c=sqlite3.connect(self.db_path,timeout=10)
        c.row_factory=sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=10000")
        return c

    def register(self,username:str,password:str) -> str:
        if not isinstance(username,str) or not 3<=len(username)<=40 or not username.isascii() or not all(x.isalnum() or x in "_-" for x in username):
            raise HubError(400,"Invalid username")
        if not isinstance(password,str) or len(password)<12 or len(password)>256:
            raise HubError(400,"Password must be 12-256 characters")
        ident=str(uuid4());salt=secrets.token_bytes(16)
        digest=hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1)
        try:
            with closing(self._db()) as c:
                with c:
                    c.execute("INSERT INTO users VALUES(?,?,?,?)",(ident,username,salt,digest))
        except sqlite3.IntegrityError: raise HubError(409,"Username already exists") from None
        return ident

    def login(self,username:str,password:str) -> str:
        with closing(self._db()) as c:
            row=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
        if not row or not hmac.compare_digest(hashlib.scrypt(str(password).encode(),salt=row["salt"],n=2**14,r=8,p=1),row["password_hash"]):
            raise HubError(401,"Invalid credentials")
        token=secrets.token_urlsafe(32)
        with closing(self._db()) as c:
            with c:
                c.execute("INSERT INTO tokens VALUES(?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),row["id"],time.time()+86400))
        return token

    def identity(self,token:str) -> str:
        if not token or len(token)>256: raise HubError(401,"Unauthorized")
        with closing(self._db()) as c:
            row=c.execute("SELECT user_id FROM tokens WHERE hash=? AND expires>?",
                          (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        if not row: raise HubError(401,"Unauthorized")
        return row["user_id"]

    def logout(self,token:str) -> None:
        if token:
            with closing(self._db()) as c:
                with c:
                    c.execute("DELETE FROM tokens WHERE hash=?",(hashlib.sha256(token.encode()).hexdigest(),))

    def create_team(self,actor:str,name:str) -> str:
        if not isinstance(name,str) or not 1<=len(name)<=80: raise HubError(400,"Invalid team name")
        ident=str(uuid4())
        with closing(self._db()) as c:
            with c:
                c.execute("INSERT INTO teams VALUES(?,?)",(ident,name))
                c.execute("INSERT INTO members VALUES(?,?,?)",(ident,actor,"owner"))
        return ident

    def require(self,actor:str,team_id:str,level:str="viewer") -> str:
        with closing(self._db()) as c:
            row=c.execute("SELECT role FROM members WHERE team_id=? AND user_id=?",(team_id,actor)).fetchone()
        if row is None or ROLE_LEVEL[row["role"]] < ROLE_LEVEL[level]:
            raise HubError(403,"Team access denied")
        return row["role"]

    def set_member(self,actor:str,team_id:str,username:str,role:str):
        actor_role=self.require(actor,team_id,"admin")
        if role not in {"viewer","editor","admin"}: raise HubError(400,"Invalid role")
        if actor_role!="owner" and role=="admin":
            raise HubError(403,"Only team owner may appoint administrators")
        with closing(self._db()) as c:
            row=c.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()
            if row is None: raise HubError(404,"User does not exist")
            with c:
                c.execute("INSERT INTO members VALUES(?,?,?) ON CONFLICT(team_id,user_id) DO UPDATE SET role=excluded.role",
                          (team_id,row["id"],role))

    def members(self,actor:str,team_id:str)->list[dict]:
        self.require(actor,team_id)
        with closing(self._db()) as c:
            rows=c.execute("SELECT users.username,members.role FROM members JOIN users ON users.id=members.user_id WHERE team_id=? ORDER BY users.username",(team_id,)).fetchall()
        return [dict(row) for row in rows]

    def read_document(self,actor:str,team_id:str,name:str)->dict:
        self.require(actor,team_id)
        if name not in {"profiles","workflows"}: raise HubError(400,"Invalid document type")
        with closing(self._db()) as c:
            row=c.execute("SELECT revision,blob FROM documents WHERE team_id=? AND name=?",(team_id,name)).fetchone()
        if not row: return {"revision":0,"blob":None}
        return {"revision":row["revision"],"blob":json.loads(row["blob"])}

    def write_document(self,actor:str,team_id:str,name:str,revision:int,blob:dict)->int:
        self.require(actor,team_id,"editor")
        if name not in {"profiles","workflows"}: raise HubError(400,"Invalid document type")
        if type(revision) is not int or revision<0: raise HubError(400,"Invalid revision")
        if not isinstance(blob,dict) or blob.get("format")!=FORMAT:
            raise HubError(400,"Only encrypted documents are accepted")
        raw=json.dumps(blob,separators=(",",":"))
        if len(raw)>MAX_DOCUMENT: raise HubError(413,"Document too large")
        # BEGIN IMMEDIATE serializes competing updates, including distinct HTTP threads.
        with closing(self._db()) as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                row=c.execute("SELECT revision FROM documents WHERE team_id=? AND name=?",(team_id,name)).fetchone()
                actual=row["revision"] if row else 0
                if actual != revision: raise HubError(409,"Revision conflict; pull before overwriting")
                c.execute("INSERT INTO documents VALUES(?,?,?,?) ON CONFLICT(team_id,name) DO UPDATE SET revision=excluded.revision,blob=excluded.blob",
                          (team_id,name,actual+1,raw))
                c.commit()
            except BaseException:
                c.rollback();raise
        return actual+1


class HubHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,hub:TeamHub):
        host=address[0]
        if host not in {"127.0.0.1","::1","localhost"}:
            raise ValueError("Only loopback binding is permitted; use a TLS reverse proxy")
        self.hub=hub
        super().__init__(address,HubHandler)


class HubHandler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        # Never log credentials, tokens, user names or encrypted metadata.
        pass

    def _json(self,status:int,data:dict):
        raw=json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(raw)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        try:
            size=int(self.headers.get("Content-Length","-1"))
            if size<0 or size>MAX_DOCUMENT+2048: raise HubError(413,"Invalid document size")
            return json.loads(self.rfile.read(size))
        except (ValueError,UnicodeDecodeError,json.JSONDecodeError):
            raise HubError(400,"Invalid JSON") from None

    def _actor(self):
        header=self.headers.get("Authorization","")
        if not header.startswith("Bearer "): raise HubError(401,"Unauthorized")
        return self.server.hub.identity(header[7:])

    def _dispatch(self):
        path=urllib.parse.urlparse(self.path)
        segments=[urllib.parse.unquote(x) for x in path.path.strip("/").split("/")]
        hub=self.server.hub
        body=self._body() if self.command in {"POST","PUT"} else {}
        if not isinstance(body,dict): raise HubError(400,"Expected JSON object")
        if segments==["register"] and self.command=="POST":
            hub.register(body.get("username"),body.get("password"));return 201,{"status":"created"}
        if segments==["login"] and self.command=="POST":
            return 200,{"token":hub.login(body.get("username"),body.get("password"))}
        actor=self._actor()
        if segments==["logout"] and self.command=="POST":
            hub.logout(self.headers.get("Authorization", "")[7:])
            return 200,{"status":"logged-out"}
        if segments==["teams"] and self.command=="POST":
            return 201,{"team_id":hub.create_team(actor,body.get("name"))}
        if len(segments)==3 and segments[0]=="teams" and segments[2]=="members":
            team_id=segments[1]
            if self.command=="GET": return 200,{"members":hub.members(actor,team_id)}
            if self.command=="POST":
                hub.set_member(actor,team_id,body.get("username"),body.get("role"));return 200,{"status":"ok"}
        if len(segments)==4 and segments[0]=="teams" and segments[2]=="documents":
            team_id,name=segments[1],segments[3]
            if self.command=="GET": return 200,hub.read_document(actor,team_id,name)
            if self.command=="PUT": return 200,{"revision":hub.write_document(actor,team_id,name,body.get("revision"),body.get("blob"))}
        raise HubError(404,"Unknown endpoint")

    def do_GET(self): self._serve()
    def do_POST(self): self._serve()
    def do_PUT(self): self._serve()

    def _serve(self):
        try: status,result=self._dispatch()
        except HubError as exc: status,result=exc.status,{"error":exc.message}
        except (sqlite3.Error,OSError) as exc:
            status,result=503,{"error":"Sync service temporarily unavailable"}
        except Exception:
            status,result=500,{"error":"Internal error"}
        self._json(status,result)


class CloudClient:
    def __init__(self,base_url:str):
        parsed=urllib.parse.urlsplit(base_url)
        if parsed.scheme not in {"https","http"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid cloud URL")
        if parsed.scheme=="http" and parsed.hostname not in {"127.0.0.1","localhost","::1"}:
            raise ValueError("Remote sync requires HTTPS")
        self.url=base_url.rstrip("/")
        self.token=None

    def request(self,method:str,path:str,data:dict|None=None):
        raw=None if data is None else json.dumps(data).encode()
        req=urllib.request.Request(self.url+path,raw,method=method,
            headers={"Content-Type":"application/json",**({"Authorization":"Bearer "+self.token} if self.token else {})})
        try:
            with urllib.request.urlopen(req,timeout=10) as resp:
                return json.loads(resp.read(MAX_DOCUMENT+4096))
        except urllib.error.HTTPError as exc:
            try: msg=json.loads(exc.read(1024)).get("error","Request failed")
            except Exception: msg="Request failed"
            raise HubError(exc.code,msg) from None

    def register(self,username,password): return self.request("POST","/register",{"username":username,"password":password})
    def login(self,username,password):
        self.token=self.request("POST","/login",{"username":username,"password":password})["token"]
        return True
    def logout(self):
        if self.token:
            try:return self.request("POST","/logout",{})
            finally:self.token=None

    def create_team(self,name): return self.request("POST","/teams",{"name":name})["team_id"]
    def set_member(self,team_id,username,role):
        return self.request("POST",f"/teams/{team_id}/members",{"username":username,"role":role})
    def members(self,team_id):return self.request("GET",f"/teams/{team_id}/members")["members"]
    def pull(self,team_id,name,passphrase):
        result=self.request("GET",f"/teams/{team_id}/documents/{name}")
        return result["revision"], (decrypt_document(result["blob"],passphrase) if result["blob"] else None)
    def push(self,team_id,name,revision,document,passphrase):
        blob=encrypt_document(document,passphrase)
        return self.request("PUT",f"/teams/{team_id}/documents/{name}",{"revision":revision,"blob":blob})["revision"]


def merge_safe_profiles(store,document:dict,*,active=lambda _:False)->int:
    """Apply explicitly allowed metadata without replacing local proxy/secret data.

    Existing IDs are updated, new IDs are added, and records absent remotely
    are NEVER deleted. Reject the whole update on validation errors.
    """
    from dataclasses import replace
    from uuid import UUID
    from .models import Profile
    keys={"id","name","group_name","tags","browser","start_url","locale","timezone_id",
          "viewport_width","viewport_height"}
    if not isinstance(document,dict) or document.get("format")!="AutumnGenLogin/profile-metadata-1":
        raise ValueError("Invalid profile metadata format")
    records=document.get("profiles")
    if not isinstance(records,list) or len(records)>2000:
        raise ValueError("Invalid profiles list")
    profiles=[]
    seen=set()
    for record in records:
        if not isinstance(record,dict) or set(record)!=keys:
            raise ValueError("Profile metadata contains unexpected fields")
        pid=str(UUID(record["id"]))
        if pid in seen:raise ValueError("Duplicate profile IDs")
        seen.add(pid)
        if active(pid):raise ValueError("Stop running profiles before importing metadata")
        try: existing=store.get(pid)
        except KeyError: existing=None
        updated=replace(existing,**record) if existing else Profile(**record)
        updated.validate()
        profiles.append(updated)
    with store._connect() as conn:
        for profile in profiles:store._save_with_connection(conn,profile)
    return len(profiles)
