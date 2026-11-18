"""AutumnGenLogin desktop entry point and CI-friendly packaged self-test."""
from __future__ import annotations

import sys
import json


def self_check() -> int:
    try:
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from autumn_genlogin.models import Profile
        from autumn_genlogin.storage import Store
        import playwright.sync_api  # noqa: F401
        import keyring  # noqa: F401

        with TemporaryDirectory() as d:
            store = Store(Path(d))
            p = store.save(Profile(name="Self-check", start_url="https://example.com"))
            if store.get(p.id).name != "Self-check":
                return 2
            store.delete(p.id)
        print("AutumnGenLogin self-check OK")
        return 0
    except Exception as exc:
        print(f"AutumnGenLogin self-check FAILED: {exc}", file=sys.stderr)
        return 1


def doctor() -> int:
    from autumn_genlogin.storage import Store
    from autumn_genlogin.diagnostics import audit_store
    report = audit_store(Store())
    if "--doctor-json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in report["checks"]:
            print(f"{item['status'].upper():4} {item['name']}: {item['detail']}")
        print("Summary:", report["summary"])
    return 1 if report["summary"]["failed"] else 0


def main() -> int:
    if "--doctor" in sys.argv or "--doctor-json" in sys.argv:
        return doctor()
    if "--self-check" in sys.argv:
        return self_check()
    import tkinter as tk
    from autumn_genlogin.ui import App
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.2)
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
