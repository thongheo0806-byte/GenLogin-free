"""Tk MiniappTabMixin controller; App provides the cross-tab service bridge."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .miniapp_signatures import publisher_fingerprint


class MiniappTabMixin:
    def _build_miniapp_tab(self, frame):
        ttk.Label(frame,text="Reviewed local Miniapps (JSON workflows, never executable packages)",
                  style="Heading.TLabel").pack(anchor="w",pady=(0,8))
        ttk.Label(frame,text="Import local JSON templates, including signed packages with separately "
                  "trusted Ed25519 keys. Preview permissions, then load a reviewed EDITABLE draft.\n"
                  "A signature proves key continuity, NOT publisher identity. No marketplace or auto-run.",
                  style="Muted.TLabel").pack(anchor="w",pady=(0,14))
        actions=ttk.Frame(frame)
        actions.pack(fill="x",pady=(0,10))
        for title,command in (("Import JSON",self.import_miniapp),
                              ("Preview",self.preview_miniapp),
                              ("Load draft",self.load_miniapp),
                              ("Remove",self.remove_miniapp)):
            ttk.Button(actions,text=title,command=command).pack(side="left",padx=(0,8))
        publisher_row=ttk.Frame(frame)
        publisher_row.pack(fill="x",pady=(0,9))
        for title,handler in (("Trust publisher key",self.trust_miniapp_publisher),
                              ("List trusted keys",self.list_miniapp_publishers),
                              ("Untrust publisher key",self.untrust_miniapp_publisher)):
            ttk.Button(publisher_row,text=title,command=handler).pack(side="left",padx=(0,8))
        self.miniapp_tree=ttk.Treeview(frame,
                columns=("name","version","category","steps","trust","origins"),
                show="headings",selectmode="browse")
        for key,title,width in (("name","Miniapp",190),("version","Version",85),
                                ("category","Category",115),("steps","Steps",65),
                                ("trust","Signature",115),
                                ("origins","Navigation origins",340)):
            self.miniapp_tree.heading(key,text=title)
            self.miniapp_tree.column(key,width=width,stretch=key in {"name","origins"})
        self.miniapp_tree.pack(fill="both",expand=True)
        self.miniapp_tree.bind("<Double-1>",lambda *_:self.preview_miniapp())
        self.refresh_miniapps()

    def trust_miniapp_publisher(self):
        label=simpledialog.askstring("Trust Miniapp signing key",
            "Enter a local label for this publisher key:",parent=self.root)
        if not label:
            return
        pub=simpledialog.askstring("Publisher Ed25519 public key",
            "Paste the 32-byte Ed25519 public key as canonical base64.\n"
            "Never paste a private key or secret.",parent=self.root)
        if not pub:
            return
        try:
            fingerprint=publisher_fingerprint(pub.strip())
            if not messagebox.askyesno("Verify publisher fingerprint OUT OF BAND",
                "This key will be TRUSTED to sign Miniapps on this machine.\n"
                "Signing only proves the holder of the private key; it does "
                "NOT prove a real organization or guarantee a safe workflow.\n\n"
                f"SHA-256 fingerprint:\n{fingerprint}\n\n"
                "Compare this fingerprint with a separately verified "
                "publisher source before trusting. Confirm?",
                parent=self.root):
                return
            self.miniapps.trust_publisher(label,pub.strip())
            self.notice("Trusted Miniapp signing key: "+fingerprint[:16])
        except Exception as exc:
            messagebox.showerror("Miniapp key",str(exc),parent=self.root)

    def list_miniapp_publishers(self):
        rows=self.miniapps.list_publishers()
        messagebox.showinfo("Locally trusted Miniapp public keys",
            "\n".join(f"{x['label']}: {x['fingerprint']}" for x in rows)
            if rows else "No publisher keys trusted.",
            parent=self.root)

    def untrust_miniapp_publisher(self):
        fingerprint=simpledialog.askstring("Untrust publisher",
            "Paste the full 64-character SHA-256 fingerprint of the key:",
            parent=self.root)
        if not fingerprint:
            return
        if not messagebox.askyesno("Revoke LOCAL Miniapp key trust",
            "Remove this key from the local trust list?\n"
            "Installed packages will remain visible but their signature "
            "status becomes 'untrusted' and they cannot load as drafts.\n"
            "This does not revoke signed files already shared elsewhere.",
            parent=self.root):
            return
        try:
            self.miniapps.untrust_publisher(fingerprint.strip())
            self.refresh_miniapps()
            self.notice("Local Miniapp signing-key trust removed")
        except Exception as exc:
            messagebox.showerror("Untrust publisher",str(exc),parent=self.root)

    def refresh_miniapps(self):
        if not hasattr(self,"miniapp_tree"):
            return
        self.miniapp_tree.delete(*self.miniapp_tree.get_children())
        for record in self.miniapps.list():
            self.miniapp_tree.insert("","end",iid=record.id,
                values=(record.name,record.version,record.category,
                        record.steps,record.signature_status,
                        ", ".join(record.origins) or "(current page)"))

    def selected_miniapp(self):
        selection=self.miniapp_tree.selection()
        if not selection:
            messagebox.showinfo("Miniapps","Select an installed miniapp first.",parent=self.root)
            return None
        return selection[0]

    def import_miniapp(self):
        path=filedialog.askopenfilename(title="Import local reviewed miniapp",
                       filetypes=[("Miniapp JSON","*.json")])
        if not path:
            return
        if not messagebox.askyesno("Untrusted workflow warning",
                "Only import JSON miniapps from trusted sources. Imported steps "
                "may navigate or click webpages after you explicitly load and run them.\n"
                "No code or script will be executed on import. Continue?",
                parent=self.root):
            return
        try:
            record=self.miniapps.install_json(Path(path))
            self.refresh_miniapps()
            self.notice(f"Imported local miniapp: {record.name} v{record.version} "
                        f"[{record.signature_status}]")
        except Exception as exc:
            messagebox.showerror("Miniapp import",str(exc),parent=self.root)

    def preview_miniapp(self):
        ident=self.selected_miniapp()
        if not ident:
            return
        try:
            record=self.miniapps._record(ident)
            doc=self.miniapps.get(ident)
            origins=sorted({s["url"].split("/",3)[0]+"//"+s["url"].split("/",3)[2]
                            for s in doc["workflow"] if s["action"]=="goto"})
            actions=", ".join(x["action"] for x in doc["workflow"])
            messagebox.showinfo("Miniapp preview",
                f"{doc['name']} v{doc['version']} ({doc['category']})\n"
                f"{doc['description']}\n\n"
                f"Signature: {record.signature_status}\n"
                f"Publisher key fingerprint: {record.publisher_fingerprint or '(none)'}\n"
                f"Navigation origins: {', '.join(origins) or '(current page)'}\n"
                f"Steps: {len(doc['workflow'])}\nActions: {actions[:750]}\n\n"
                "The miniapp will never run automatically.",
                parent=self.root)
        except Exception as exc:
            messagebox.showerror("Miniapp preview",str(exc),parent=self.root)

    def load_miniapp(self):
        ident=self.selected_miniapp()
        if not ident:
            return
        try:
            record=self.miniapps._record(ident)
            if record.signature_status=="untrusted":
                raise ValueError("Previously trusted signing key was removed. "
                                 "Re-establish trust out of band before loading.")
            preview=", ".join(record.origins) or "(currently open webpage)"
            if not messagebox.askyesno("Load miniapp draft",
                 f"Load '{record.name}' v{record.version} as a new editable workflow draft?\n\n"
                 f"Navigation origins: {preview}\nSteps: {record.steps}\n"
                 f"Signature: {record.signature_status}\n"
                 f"Publisher fingerprint: {record.publisher_fingerprint or '(none)'}\n\n"
                 "Unsigned packages do NOT verify publisher identity. "
                 "Review clicks, input placeholders and page permissions before running. "
                 "Your current workflow editor contents will be replaced.",
                 parent=self.root):
                return
            doc=self.miniapps.get(ident)
            self.load_workflow_draft(doc["workflow"])
            self.notice(f"Loaded miniapp draft: {record.name}; not executed")
        except Exception as exc:
            messagebox.showerror("Miniapp load",str(exc),parent=self.root)

    def remove_miniapp(self):
        ident=self.selected_miniapp()
        if not ident:
            return
        try:
            record=self.miniapps._record(ident)
            if messagebox.askyesno("Remove miniapp",
                    f"Remove local template '{record.name}' v{record.version}? "
                    "Existing exported workflow files are unaffected.",parent=self.root):
                self.miniapps.remove(ident)
                self.refresh_miniapps()
                self.notice("Local miniapp template removed")
        except Exception as exc:
            messagebox.showerror("Remove miniapp",str(exc),parent=self.root)

