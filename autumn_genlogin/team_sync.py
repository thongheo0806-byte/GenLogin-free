"""Optional self-hosted encrypted metadata sync with team access controls.

No cookies, passwords, tokens, extension binaries or browser data are synced.
The server stores opaque AES-GCM ciphertext; a passphrase stays on clients.
Server defaults to loopback; place behind a TLS reverse proxy for remote use.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

FORMAT = "AutumnGenLogin/encrypted-1"
MAX_DOCUMENT = 1024 * 1024
# Old Hub users/documents used unversioned scrypt 2**14. New writes use
# 2**15 and bind the exact versioned KDF parameters into AES-GCM AAD.
# Bounds prevent malicious envelopes from requesting unbounded CPU/RAM.
LEGACY_SCRYPT_LOG_N = 14
CURRENT_SCRYPT_LOG_N = 15
MAX_SCRYPT_LOG_N = 17
SCRYPT_MAXMEM = 256 * 1024 * 1024
SCRYPT_R = 8
SCRYPT_P = 1
# Shared across Hub instances in this process; fail fast instead of queuing
# unbounded request threads behind memory-hard authentication work.
AUTH_KDF_SLOTS = 4
_AUTH_SLOTS = threading.BoundedSemaphore(AUTH_KDF_SLOTS)
_DUMMY_AUTH_SALT = secrets.token_bytes(16)
_DUMMY_AUTH_DIGEST = bytes(64)
ENVELOPE_FIELDS = frozenset({"format", "salt", "nonce", "ciphertext"})

# Bound damage by a single compromised editor even if team-wide quota remains.
MAX_MEMBER_SESSION_DOCUMENTS = 256
MAX_MEMBER_SESSION_BYTES = 64 * 1024 * 1024
REQUEST_IO_TIMEOUT = 2.0
ROLE_LEVEL = {"viewer":0, "editor":1,"admin":2,"owner":3}
# Whitelist immutable, opaque session-archive parts and the final manifest.
# No arbitrary document names, paths, query strings or token-like values.
_SESSION_NAME = re.compile(
    r"session-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-(?:[0-9]{2}|manifest)\Z"
)


def _allowed_document_name(name: str) -> bool:
    return name in {"profiles","workflows"} or (
        isinstance(name,str) and bool(_SESSION_NAME.fullmatch(name))
    )


def _b64(v:bytes) -> str:
    return base64.b64encode(v).decode("ascii")


def _unb64(v:str) -> bytes:
    if not isinstance(v,str) or len(v) > MAX_DOCUMENT*2: raise ValueError("Invalid encoded data")
    return base64.b64decode(v,validate=True)


def _scrypt_key(secret: str, salt: bytes, *, log_n: int,
                dklen: int = 32) -> bytes:
    if type(log_n) is not int or not LEGACY_SCRYPT_LOG_N <= log_n <= MAX_SCRYPT_LOG_N:
        raise ValueError("Unsupported scrypt work factor")
    return hashlib.scrypt(
        secret.encode("utf-8"), salt=salt, n=1 << log_n,
        r=SCRYPT_R, p=SCRYPT_P, dklen=dklen, maxmem=SCRYPT_MAXMEM)


@contextmanager
def _auth_slot():
    if not _AUTH_SLOTS.acquire(blocking=False):
        raise HubError(503, "Authentication temporarily busy; retry later")
    try:
        yield
    finally:
        _AUTH_SLOTS.release()


def _envelope_kdf(blob: object) -> tuple[int, bytes]:
    """Validate bounded KDF metadata and return (log_n, authenticated AAD).

    Legacy ciphertext had no KDF field and authenticated only FORMAT.
    New ciphertext authenticates the canonical KDF header as well so the
    work factor cannot be silently changed after encryption.
    """
    if not isinstance(blob, dict) or blob.get("format") != FORMAT:
        raise ValueError("Invalid encrypted document")
    fields = set(blob)
    if fields == ENVELOPE_FIELDS:
        return LEGACY_SCRYPT_LOG_N, FORMAT.encode()
    if fields != (ENVELOPE_FIELDS | {"kdf"}):
        raise ValueError("Invalid encrypted document fields")
    kdf = blob["kdf"]
    if (not isinstance(kdf, dict) or set(kdf) != {"name", "log_n", "r", "p"}
            or kdf["name"] != "scrypt" or type(kdf["log_n"]) is not int
            or not LEGACY_SCRYPT_LOG_N <= kdf["log_n"] <= MAX_SCRYPT_LOG_N
            or type(kdf["r"]) is not int or kdf["r"] != SCRYPT_R
            or type(kdf["p"]) is not int or kdf["p"] != SCRYPT_P):
        raise ValueError("Unsupported encrypted document KDF")
    encoded = json.dumps(kdf, sort_keys=True, separators=(",", ":")).encode()
    return kdf["log_n"], FORMAT.encode() + b"|kdf|" + encoded


def _validate_encrypted_envelope(blob: object) -> None:
    """Check the envelope structure; only clients can authenticate ciphertext."""
    try:
        _envelope_kdf(blob)
        salt, nonce, ciphertext = (_unb64(blob[k]) for k in ("salt", "nonce", "ciphertext"))
    except (KeyError, ValueError, TypeError, binascii.Error):
        raise HubError(400, "Invalid encrypted document envelope") from None
    if len(salt) != 16 or len(nonce) != 12 or not 18 <= len(ciphertext) <= MAX_DOCUMENT:
        raise HubError(400, "Invalid encrypted document envelope")


def encrypt_document(data: dict, passphrase: str) -> dict:
    """Encrypt JSON with a versioned, authenticated work factor."""
    if not isinstance(passphrase, str) or len(passphrase) < 12:
        raise ValueError("Sync passphrase needs at least 12 characters")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    kdf = {"name": "scrypt", "log_n": CURRENT_SCRYPT_LOG_N,
           "r": SCRYPT_R, "p": SCRYPT_P}
    envelope = {"format": FORMAT, "salt": _b64(salt), "nonce": _b64(nonce),
                "kdf": kdf}
    _, aad = _envelope_kdf({**envelope, "ciphertext": ""})
    key = _scrypt_key(passphrase, salt, log_n=CURRENT_SCRYPT_LOG_N)
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode()
    if len(raw) > MAX_DOCUMENT // 2:
        raise ValueError("Sync document too large")
    envelope["ciphertext"] = _b64(AESGCM(key).encrypt(nonce, raw, aad))
    return envelope


def decrypt_document(blob: dict, passphrase: str) -> dict:
    if not isinstance(passphrase, str) or len(passphrase) < 12:
        raise ValueError("Sync passphrase needs at least 12 characters")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    log_n, aad = _envelope_kdf(blob)
    salt, nonce, encrypted = (_unb64(blob[k]) for k in ("salt", "nonce", "ciphertext"))
    if len(salt) != 16 or len(nonce) != 12 or not 18 <= len(encrypted) <= MAX_DOCUMENT:
        raise ValueError("Invalid encryption parameters")
    key = _scrypt_key(passphrase, salt, log_n=log_n)
    plaintext = AESGCM(key).decrypt(nonce, encrypted, aad)
    doc = json.loads(plaintext)
    if not isinstance(doc, dict):
        raise ValueError("Invalid document")
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
                    salt BLOB NOT NULL,password_hash BLOB NOT NULL,
                    password_kdf_log_n INTEGER NOT NULL DEFAULT 14);
                CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,
                    expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY,name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS members(team_id TEXT NOT NULL,user_id TEXT NOT NULL,
                    role TEXT NOT NULL,PRIMARY KEY(team_id,user_id));
                CREATE TABLE IF NOT EXISTS documents(team_id TEXT NOT NULL,name TEXT NOT NULL,
                    revision INTEGER NOT NULL,blob TEXT NOT NULL,
                    creator_id TEXT NOT NULL DEFAULT '',PRIMARY KEY(team_id,name));
                CREATE TABLE IF NOT EXISTS revoked_sessions(team_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,revoked_at REAL NOT NULL,
                    PRIMARY KEY(team_id,session_id));
            """)
            # Additive migrations preserve stored legacy password hashes and
            # encrypted archives; successful logins upgrade old password hashes.
            columns={row["name"] for row in c.execute("PRAGMA table_info(documents)")}
            if "creator_id" not in columns:
                c.execute("ALTER TABLE documents ADD COLUMN creator_id TEXT NOT NULL DEFAULT ''")
            user_columns={row["name"] for row in c.execute("PRAGMA table_info(users)")}
            if "password_kdf_log_n" not in user_columns:
                c.execute("ALTER TABLE users ADD COLUMN password_kdf_log_n "
                          "INTEGER NOT NULL DEFAULT 14")
            c.commit()

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
        with _auth_slot():
            digest=_scrypt_key(password, salt, log_n=CURRENT_SCRYPT_LOG_N, dklen=64)
        try:
            with closing(self._db()) as c:
                with c:
                    c.execute("INSERT INTO users "
                              "(id,username,salt,password_hash,password_kdf_log_n) "
                              "VALUES(?,?,?,?,?)",
                              (ident,username,salt,digest,CURRENT_SCRYPT_LOG_N))
        except sqlite3.IntegrityError: raise HubError(409,"Username already exists") from None
        return ident

    def login(self,username:str,password:str) -> str:
        # Reject malformed/oversized inputs independent of account existence.
        if (not isinstance(username,str) or not 3<=len(username)<=40
                or not isinstance(password,str) or len(password)>256):
            raise HubError(401,"Invalid credentials")
        with closing(self._db()) as c:
            row=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
        log_n=row["password_kdf_log_n"] if row is not None else None
        usable=(row is not None and type(log_n) is int
                and LEGACY_SCRYPT_LOG_N <= log_n <= MAX_SCRYPT_LOG_N
                and isinstance(row["salt"],bytes) and len(row["salt"])==16
                and isinstance(row["password_hash"],bytes)
                and len(row["password_hash"])==64)
        with _auth_slot():
            # Unknown accounts perform the same current-cost derivation and
            # constant-time digest comparison as current registered accounts.
            factor=log_n if usable else CURRENT_SCRYPT_LOG_N
            salt=row["salt"] if usable else _DUMMY_AUTH_SALT
            expected=row["password_hash"] if usable else _DUMMY_AUTH_DIGEST
            candidate=_scrypt_key(password,salt,log_n=factor,dklen=64)
            matches=hmac.compare_digest(candidate,expected)
            valid=usable and matches
            if usable and log_n==LEGACY_SCRYPT_LOG_N:
                # Two legacy derivations approximate the current work factor.
                # This reduces, but cannot mathematically eliminate, timing
                # differences across legacy and current KDFs or DB caches.
                _scrypt_key(password,_DUMMY_AUTH_SALT,
                            log_n=LEGACY_SCRYPT_LOG_N,dklen=64)
            if not valid:
                raise HubError(401,"Invalid credentials")
            new_salt=upgraded=None
            if log_n<CURRENT_SCRYPT_LOG_N:
                new_salt=secrets.token_bytes(16)
                upgraded=_scrypt_key(password,new_salt,
                                     log_n=CURRENT_SCRYPT_LOG_N,dklen=64)
        token=secrets.token_urlsafe(32)
        with closing(self._db()) as c:
            with c:
                if upgraded is not None:
                    # KDF computation finished before acquiring a DB writer
                    # lock. CAS preserves concurrent upgrades.
                    c.execute(
                        "UPDATE users SET salt=?,password_hash=?,password_kdf_log_n=? "
                        "WHERE id=? AND salt=? AND password_hash=? "
                        "AND password_kdf_log_n=?",
                        (new_salt,upgraded,CURRENT_SCRYPT_LOG_N,row["id"],
                         row["salt"],row["password_hash"],log_n))
                c.execute("INSERT INTO tokens VALUES(?,?,?)",
                          (hashlib.sha256(token.encode()).hexdigest(),
                           row["id"],time.time()+86400))
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
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()
            if row is None: raise HubError(404,"User does not exist")
            existing=c.execute("SELECT role FROM members WHERE team_id=? AND user_id=?",(team_id,row["id"])).fetchone()
            # Owners are not demotable through membership administration; this
            # also blocks any malicious admin from locking out the creator.
            if existing and existing["role"] == "owner":
                raise HubError(403,"The team owner cannot be reassigned")
            # Administrators cannot change a peer administrator; owner only.
            if existing and existing["role"] == "admin" and actor_role != "owner":
                raise HubError(403,"Only the owner may manage administrators")
            c.execute("INSERT INTO members VALUES(?,?,?) ON CONFLICT(team_id,user_id) DO UPDATE SET role=excluded.role",
                      (team_id,row["id"],role))
            c.commit()

    def members(self,actor:str,team_id:str)->list[dict]:
        self.require(actor,team_id)
        with closing(self._db()) as c:
            rows=c.execute("SELECT users.username,members.role FROM members JOIN users ON users.id=members.user_id WHERE team_id=? ORDER BY users.username",(team_id,)).fetchall()
        return [dict(row) for row in rows]

    def read_document(self,actor:str,team_id:str,name:str)->dict:
        self.require(actor,team_id)
        if not _allowed_document_name(name): raise HubError(400,"Invalid document type")
        with closing(self._db()) as c:
            match=_SESSION_NAME.fullmatch(name) if name.startswith("session-") else None
            if match and c.execute(
                "SELECT 1 FROM revoked_sessions WHERE team_id=? AND session_id=?",
                (team_id,match.group(1))).fetchone():
                raise HubError(410,"Encrypted session handoff revoked")
            row=c.execute("SELECT revision,blob FROM documents WHERE team_id=? AND name=?",(team_id,name)).fetchone()
        if not row: return {"revision":0,"blob":None}
        return {"revision":row["revision"],"blob":json.loads(row["blob"])}

    def write_document(self,actor:str,team_id:str,name:str,revision:int,blob:dict)->int:
        self.require(actor,team_id,"editor")
        if not _allowed_document_name(name): raise HubError(400,"Invalid document type")
        if type(revision) is not int or revision<0: raise HubError(400,"Invalid revision")
        _validate_encrypted_envelope(blob)
        raw=json.dumps(blob,separators=(",",":"))
        if len(raw.encode("utf-8"))>MAX_DOCUMENT: raise HubError(413,"Document too large")
        # BEGIN IMMEDIATE serializes competing updates, including distinct HTTP threads.
        with closing(self._db()) as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                current=c.execute(
                    "SELECT role FROM members WHERE team_id=? AND user_id=?",
                    (team_id,actor)).fetchone()
                if current is None or ROLE_LEVEL[current["role"]] < ROLE_LEVEL["editor"]:
                    raise HubError(403,"Team access denied")
                row=c.execute("SELECT revision FROM documents WHERE team_id=? AND name=?",(team_id,name)).fetchone()
                actual=row["revision"] if row else 0
                if actual != revision: raise HubError(409,"Revision conflict; pull before overwriting")
                # Session parts/manifests are immutable; a writer cannot
                # rewrite an already-published encrypted backup.
                match=_SESSION_NAME.fullmatch(name) if name.startswith("session-") else None
                if match and c.execute(
                    "SELECT 1 FROM revoked_sessions WHERE team_id=? AND session_id=?",
                    (team_id,match.group(1))).fetchone():
                    raise HubError(410,"Encrypted session handoff revoked")
                if name.startswith("session-") and row is not None:
                    raise HubError(409,"Published session archive documents are immutable")
                if name.startswith("session-"):
                    count=c.execute(
                        "SELECT COUNT(*) FROM documents WHERE team_id=? AND name LIKE 'session-%'",
                        (team_id,)).fetchone()[0]
                    if count>=2048:
                        raise HubError(413,"Team archive storage quota exceeded")
                    owned=c.execute(
                        "SELECT COUNT(*) AS documents,COALESCE(SUM(LENGTH(blob)),0) AS bytes "
                        "FROM documents WHERE team_id=? AND creator_id=? "
                        "AND name LIKE 'session-%'", (team_id,actor)).fetchone()
                    if (owned["documents"]>=MAX_MEMBER_SESSION_DOCUMENTS or
                            owned["bytes"]+len(raw.encode("utf-8"))>MAX_MEMBER_SESSION_BYTES):
                        raise HubError(413,"Member archive storage quota exceeded")
                c.execute(
                    "INSERT INTO documents(team_id,name,revision,blob,creator_id) "
                    "VALUES(?,?,?,?,?) ON CONFLICT(team_id,name) "
                    "DO UPDATE SET revision=excluded.revision,blob=excluded.blob",
                    (team_id,name,actual+1,raw,actor))
                c.commit()
            except BaseException:
                c.rollback();raise
        return actual+1


    def list_sessions(self, actor: str, team_id: str) -> list[dict]:
        """Admin-only discovery for cleanup of orphan or abusive archives."""
        self.require(actor, team_id, "admin")
        with closing(self._db()) as c:
            rows=c.execute(
                "SELECT d.name,LENGTH(d.blob) AS bytes,u.username "
                "FROM documents d LEFT JOIN users u ON u.id=d.creator_id "
                "WHERE d.team_id=? AND d.name LIKE 'session-%' ORDER BY d.name",
                (team_id,)).fetchall()
        sessions={}
        for row in rows:
            match=_SESSION_NAME.fullmatch(row["name"])
            if match is None:
                continue
            sid=match.group(1)
            entry=sessions.setdefault(sid, {
                "session_id":sid, "documents":0, "stored_bytes":0,
                "has_manifest":False, "uploaders":set()
            })
            entry["documents"]+=1
            entry["stored_bytes"]+=row["bytes"]
            entry["has_manifest"] |= row["name"].endswith("-manifest")
            if row["username"] is not None:
                entry["uploaders"].add(row["username"])
        return [
            {**entry, "uploaders":sorted(entry["uploaders"])}
            for _sid,entry in sorted(sessions.items())
        ]

    def revoke_session(self, actor:str, team_id:str, session_id:str) -> int:
        """Owner/admin can atomically tombstone an archive and purge its ciphertext.

        A tombstone prevents re-publishing an identical ID after purge.
        The server cannot revoke copies downloaded before revocation.
        """
        self.require(actor,team_id,"admin")
        try:
            canonical=str(UUID(session_id))
        except (TypeError,ValueError,AttributeError):
            raise HubError(400,"Invalid session handoff ID") from None
        if session_id != canonical:
            raise HubError(400,"Session handoff ID must be canonical lowercase UUID")
        with closing(self._db()) as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                current=c.execute(
                    "SELECT role FROM members WHERE team_id=? AND user_id=?",
                    (team_id,actor)).fetchone()
                if current is None or ROLE_LEVEL[current["role"]] < ROLE_LEVEL["admin"]:
                    raise HubError(403,"Team access denied")
                c.execute("INSERT OR IGNORE INTO revoked_sessions VALUES(?,?,?)",
                          (team_id,canonical,time.time()))
                removed=c.execute(
                    "DELETE FROM documents WHERE team_id=? AND name LIKE ?",
                    (team_id,"session-"+canonical+"-%")).rowcount
                c.commit()
            except BaseException:
                c.rollback()
                raise
        return removed


class HubHTTPServer(ThreadingHTTPServer):
    # Request handlers own short-lived SQLite connections. Windows cannot
    # delete the hub database while a daemon request thread remains alive.
    daemon_threads=False
    block_on_close=True
    def __init__(self,address,hub:TeamHub):
        host=address[0]
        if host not in {"127.0.0.1","::1","localhost"}:
            raise ValueError("Only loopback binding is permitted; use a TLS reverse proxy")
        self.hub=hub
        super().__init__(address,HubHandler)


class HubHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        # A client that stalls mid-header or mid-body must not pin a handler.
        self.connection.settimeout(REQUEST_IO_TIMEOUT)

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
        anonymous=self.command=="POST" and segments in (["register"], ["login"])
        # Authorize before reading potentially slow request bodies whenever possible.
        actor=None if anonymous else self._actor()
        body=self._body() if self.command in {"POST","PUT"} else {}
        if not isinstance(body,dict): raise HubError(400,"Expected JSON object")
        if segments==["register"] and self.command=="POST":
            hub.register(body.get("username"),body.get("password"));return 201,{"status":"created"}
        if segments==["login"] and self.command=="POST":
            return 200,{"token":hub.login(body.get("username"),body.get("password"))}
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
        if len(segments)==3 and segments[0]=="teams" and segments[2]=="sessions":
            if self.command=="GET":
                return 200,{"sessions":hub.list_sessions(actor,segments[1])}
        if len(segments)==4 and segments[0]=="teams" and segments[2]=="sessions":
            if self.command=="DELETE":
                count=hub.revoke_session(actor,segments[1],segments[3])
                return 200,{"status":"revoked","deleted_documents":count}
        if len(segments)==4 and segments[0]=="teams" and segments[2]=="documents":
            team_id,name=segments[1],segments[3]
            if self.command=="GET": return 200,hub.read_document(actor,team_id,name)
            if self.command=="PUT": return 200,{"revision":hub.write_document(actor,team_id,name,body.get("revision"),body.get("blob"))}
        raise HubError(404,"Unknown endpoint")

    def do_GET(self): self._serve()
    def do_POST(self): self._serve()
    def do_PUT(self): self._serve()
    def do_DELETE(self): self._serve()

    def _serve(self):
        try: status,result=self._dispatch()
        except HubError as exc: status,result=exc.status,{"error":exc.message}
        except (sqlite3.Error,OSError) as exc:
            status,result=503,{"error":"Sync service temporarily unavailable"}
        except Exception:
            status,result=500,{"error":"Internal error"}
        self._json(status,result)


class _RejectCloudRedirects(urllib.request.HTTPRedirectHandler):
    """API redirects can forward bearer credentials to an unrelated host.

    Sync endpoints have a fixed API origin and must not redirect, even to
    another HTTPS URL. Reject all 30x responses before a follow-up request.
    """
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HubError(502, "Cloud sync API redirects are not permitted")


class CloudClient:
    def __init__(self,base_url:str):
        parsed=urllib.parse.urlsplit(base_url)
        if parsed.scheme not in {"https","http"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid cloud URL")
        if parsed.scheme=="http" and parsed.hostname not in {"127.0.0.1","localhost","::1"}:
            raise ValueError("Remote sync requires HTTPS")
        self.url=base_url.rstrip("/")
        self.token=None
        # Do not use urlopen's global redirect handler: urllib may copy an
        # Authorization header across origins (and even to plaintext HTTP).
        self._opener=urllib.request.build_opener(_RejectCloudRedirects())

    def request(self,method:str,path:str,data:dict|None=None):
        raw=None if data is None else json.dumps(data).encode()
        req=urllib.request.Request(self.url+path,raw,method=method,
            headers={"Content-Type":"application/json",**({"Authorization":"Bearer "+self.token} if self.token else {})})
        try:
            with self._opener.open(req,timeout=10) as resp:
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
    def list_sessions(self,team_id):
        return self.request("GET",f"/teams/{team_id}/sessions")["sessions"]
    def revoke_session(self,team_id,session_id):
        try:
            canonical=str(UUID(session_id))
        except (ValueError,TypeError,AttributeError):
            raise ValueError("Invalid session handoff ID") from None
        if session_id != canonical:
            raise ValueError("Session handoff ID must be canonical lowercase UUID")
        return self.request("DELETE",f"/teams/{team_id}/sessions/{canonical}")
    def pull(self,team_id,name,passphrase):
        result=self.request("GET",f"/teams/{team_id}/documents/{name}")
        return result["revision"], (decrypt_document(result["blob"],passphrase) if result["blob"] else None)
    def push(self,team_id,name,revision,document,passphrase):
        blob=encrypt_document(document,passphrase)
        return self.request("PUT",f"/teams/{team_id}/documents/{name}",{"revision":revision,"blob":blob})["revision"]


def merge_safe_profiles(store,document:dict,*,active=lambda _:False,
                        expected_local:dict | None = None)->int:
    """Transactionally apply reviewed cloud metadata without overwriting secrets.

    A pull may pass expected_local to assert its preview is still current.
    Check and apply under the SAME SQLite write transaction: local edits from
    another GUI/API thread can never be silently lost between review and save.
    """
    from dataclasses import replace
    from uuid import UUID
    from .models import Profile
    from .cloud_merge import _profiles
    keys={"id","name","group_name","tags","browser","start_url","locale","timezone_id",
          "viewport_width","viewport_height"}
    if not isinstance(document,dict) or document.get("format")!="AutumnGenLogin/profile-metadata-1":
        raise ValueError("Invalid profile metadata format")
    records=document.get("profiles")
    if not isinstance(records,list) or len(records)>2000:
        raise ValueError("Invalid profiles list")
    normalized=[]
    seen=set()
    for record in records:
        if not isinstance(record,dict) or set(record)!=keys:
            raise ValueError("Profile metadata contains unexpected fields")
        pid=str(UUID(record["id"]))
        if record["id"]!=pid or pid in seen:
            raise ValueError("Duplicate or noncanonical profile IDs")
        seen.add(pid)
        normalized.append(record)
    if expected_local is not None:
        _profiles(expected_local)
    with store.transaction() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if expected_local is not None:
            # Do not query Store.all() from a second connection. Comparing in
            # the write transaction closes the edit-after-preview race.
            current={"format":"AutumnGenLogin/profile-metadata-1",
                     "profiles":[
                         {k:getattr(p,k) for k in keys}
                         for p in (Profile(**dict(row)) for row in
                                   conn.execute("SELECT * FROM profiles"))
                     ]}
            if _profiles(current)!=_profiles(expected_local):
                raise ValueError("Local profile metadata changed since cloud preview; review again")
        profiles=[]
        for record in normalized:
            pid=record["id"]
            if active(pid):
                raise ValueError("Stop running profiles before importing metadata")
            row=conn.execute("SELECT * FROM profiles WHERE id = ?",(pid,)).fetchone()
            existing=Profile(**dict(row)) if row is not None else None
            updated=replace(existing,**record) if existing else Profile(**record)
            updated.validate()
            profiles.append(updated)
        for profile in profiles:
            store._save_with_connection(conn,profile)
    return len(profiles)
