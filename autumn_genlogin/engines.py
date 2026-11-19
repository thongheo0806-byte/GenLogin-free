"""Playwright-backed engine capability matrix and launch configuration."""
from __future__ import annotations

from .models import Profile

ENGINE_CAPABILITIES = {
    "chromium": {"type": "chromium", "channel": "chromium", "extensions": True},
    "chrome":   {"type": "chromium", "channel": "chrome", "extensions": False},
    "msedge":   {"type": "chromium", "channel": "msedge", "extensions": False},
    "firefox":  {"type": "firefox", "channel": None, "extensions": False},
    "webkit":   {"type": "webkit", "channel": None, "extensions": False},
}


def browser_options(profile:Profile, user_data_dir:str, *, headless:bool, extension_paths=(), proxy_password=""):
    profile.validate()
    engine=ENGINE_CAPABILITIES[profile.browser]
    if extension_paths and not engine["extensions"]:
        raise ValueError("Unpacked extensions require bundled Playwright Chromium")
    opts={"user_data_dir":user_data_dir,"headless":headless,
          "locale":profile.locale,"timezone_id":profile.timezone_id,
          "viewport":{"width":profile.viewport_width,"height":profile.viewport_height},
          "accept_downloads":True}
    if engine["channel"]: opts["channel"]=engine["channel"]
    if profile.user_agent: opts["user_agent"]=profile.user_agent
    if profile.proxy_scheme:
        host=profile.proxy_host
        if ":" in host and not host.startswith("["):host="["+host+"]"
        proxy={"server":f"{profile.proxy_scheme}://{host}:{profile.proxy_port}"}
        if profile.proxy_username:
            proxy["username"]=profile.proxy_username
            if proxy_password: proxy["password"]=proxy_password
        opts["proxy"]=proxy
    if extension_paths:
        paths=",".join(str(path) for path in extension_paths)
        opts["args"]=["--disable-extensions-except="+paths,"--load-extension="+paths]
    return engine["type"], opts
