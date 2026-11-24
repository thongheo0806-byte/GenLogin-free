"""Tk cloud controller: encrypted metadata and manual archive handoff.

Worker tasks must capture Tk values on the UI thread before submission.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .cloud_sessions import CloudSessionHandoff
from .team_sync import CloudClient, safe_profile_metadata
from .models import validated_steps


class CloudTabMixin:
    def _build_cloud_tab(self,frame):
        ttk.Label(frame, text="Opt-in encrypted team sync and manual archive handoff",style="Heading.TLabel").pack(anchor="w", pady=8)
        ttk.Label(frame, text="Requires self-hosted server (python main.py --hub), HTTPS for remote access.\n"
                  "Metadata/workflows exclude sessions; sensitive encrypted .aglb session backup upload "
                  "is OPTIONAL and must be explicitly confirmed. Never sync open browser state.",
                  style="Muted.TLabel").pack(anchor="w",pady=8)
        self.cloud_fields={}
        for title,name,default,secret in (("Server URL","url","http://127.0.0.1:8899",False),
                    ("User","username","",False),("Password","password","",True),
                    ("Team ID","team_id","",False),("Shared encryption passphrase","passphrase","",True)):
            box=ttk.Frame(frame);box.pack(fill="x",pady=4)
            ttk.Label(box,text=title,width=28).pack(side="left")
            var=tk.StringVar(value=default)
            ttk.Entry(box,textvariable=var,show="*" if secret else "",width=60).pack(side="left",fill="x",expand=True)
            self.cloud_fields[name]=var
        row=ttk.Frame(frame);row.pack(fill="x",pady=12)
        for title,action in (("Register",self.cloud_register),("Login",self.cloud_login),
                             ("Create team",self.cloud_create_team),("Invite member",self.cloud_invite),
                             ("Push metadata",lambda:self.cloud_sync("profiles","push")),
                             ("Pull metadata",lambda:self.cloud_sync("profiles","pull")),
                             ("Push workflow",lambda:self.cloud_sync("workflows","push")),
                             ("Pull workflow",lambda:self.cloud_sync("workflows","pull"))):
            ttk.Button(row,text=title,command=action).pack(side="left",padx=3)
        archive_row=ttk.Frame(frame)
        archive_row.pack(fill="x",pady=(5,8))
        ttk.Button(archive_row,text="Upload encrypted session backup",
                   command=self.cloud_upload_session).pack(side="left",padx=(0,9))
        ttk.Button(archive_row,text="Download encrypted session backup",
                   command=self.cloud_download_session).pack(side="left",padx=(0,9))
        ttk.Button(archive_row,text="Revoke team archive",
                   command=self.cloud_revoke_session).pack(side="left")
        archive_tools=ttk.Frame(frame)
        archive_tools.pack(fill="x",pady=(1,8))
        ttk.Button(archive_tools,text="Resume interrupted encrypted backup upload",
                   command=self.cloud_resume_upload_session).pack(side="left",padx=(0,12))
        ttk.Button(archive_tools,text="List team archives (admin)",
                   command=self.cloud_list_sessions).pack(side="left")
        self.cloud_status=tk.StringVar(value="Not signed in")
        ttk.Label(frame,textvariable=self.cloud_status).pack(anchor="w")
        ttk.Label(frame,text="Remote team roles: owner, admin, editor, viewer. Push uses revision checks to reject conflicts.",style="Muted.TLabel").pack(anchor="w",pady=8)

    def _cloud_action(self,fn,finished=None):
        # Tk widgets and after() must never be touched from a network worker.
        # Reuse the queue drained exclusively on the GUI main thread.
        self._run_ui_task(
            fn,
            finished or (lambda _:self.cloud_status.set("Success")),
            title="Team sync",
            failed=lambda message:messagebox.showerror(
                "Team sync",message,parent=self.root),
        )

    def cloud_upload_session(self):
        # Preassign an ID so a failed upload can be resumed after restart.
        self._cloud_upload_session(str(uuid4()),resuming=False)

    def cloud_resume_upload_session(self):
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        ident=simpledialog.askstring("Resume encrypted backup upload",
            "Enter the original 36-character handoff ID.\n"
            "You must select EXACTLY the same encrypted .aglb file and "
            "use the same TEAM passphrase.\n"
            "A mismatch will be rejected, never overwritten.",parent=self.root)
        if ident:
            self._cloud_upload_session(ident.strip(),resuming=True)

    def _cloud_upload_session(self,ident,resuming=False):
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        source=filedialog.askopenfilename(title="Select the already encrypted .aglb backup",
                   filetypes=[("Autumn encrypted backup","*.aglb")])
        if not source:
            return
        team_id=self.cloud_fields["team_id"].get().strip()
        passphrase=self.cloud_fields["passphrase"].get()
        if len(passphrase)<12:
            return messagebox.showerror("Session backup",
                "Enter a strong shared TEAM encryption passphrase.",parent=self.root)
        warning=("RESUME a previously interrupted transfer" if resuming
                 else "UPLOAD a sensitive encrypted browser session")
        if not messagebox.askyesno(warning,
                "You are sharing an encrypted archive containing cookies, "
                "saved sessions and local storage.\n\n"
                "The backup is already encrypted with its own archive password "
                "and will be encrypted again with the TEAM password.\n"
                "Members with both passwords and access can restore it.\n\n"
                f"Transfer ID: {ident}\n"
                "Copy this ID before starting so you can resume if interrupted.\n"
                "Use only a backup from a STOPPED profile. Continue?",
                parent=self.root):
            return
        # The ID must be available BEFORE the background worker sends data.
        # Clipboard contains only random UUID, never credentials or a password.
        self.root.clipboard_clear()
        self.root.clipboard_append(ident)
        self.cloud_status.set("Encrypted transfer ID copied (keep for retries): "+ident)

        def task():
            return CloudSessionHandoff(self.cloud).upload(
                team_id,Path(source),passphrase,session_id=ident)
        def finished(actual_id):
            self.cloud_status.set("Encrypted archive published: "+actual_id)
            messagebox.showinfo("Encrypted backup uploaded",
                "The encrypted backup was published to the team.\n"
                "Transfer UUID: "+actual_id+"\n\n"
                "This was a manual file handoff, not live session sync.\n"
                "You may retry a completed transfer with the same file: "
                "the server's contents will be verified but NOT overwritten.",
                parent=self.root)
        self._cloud_action(task,finished)

    def cloud_download_session(self):
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        ident=simpledialog.askstring("Encrypted session handoff",
                 "Paste the 36-character archive transfer UUID:",parent=self.root)
        if not ident:
            return
        dest=filedialog.asksaveasfilename(title="Save encrypted backup only",
                defaultextension=".aglb",filetypes=[("Autumn encrypted backup","*.aglb")])
        if not dest:
            return
        team_id=self.cloud_fields["team_id"].get().strip()
        passphrase=self.cloud_fields["passphrase"].get()
        if len(passphrase)<12:
            return messagebox.showerror("Session backup","Enter the TEAM encryption passphrase.",
                                        parent=self.root)
        if not messagebox.askyesno("Download sensitive encrypted backup",
                "Download this encrypted session backup to a NEW local file?\n"
                "It will NOT be decrypted or automatically installed.\n"
                "Restore manually through 'Restore backup' using the original "
                "archive passphrase only after reviewing the file.",
                parent=self.root):
            return
        def task():
            return CloudSessionHandoff(self.cloud).download(
                team_id,ident,Path(dest),passphrase)
        def finished(size):
            self.cloud_status.set(f"Encrypted backup downloaded ({size} bytes); not restored")
            messagebox.showinfo("Encrypted archive downloaded",
                "Only encrypted .aglb bytes were saved.\n"
                "Use Restore backup separately with the original archive passphrase "
                "to create a NEW local profile. No existing profile is overwritten.",
                parent=self.root)
        self._cloud_action(task,finished)

    def cloud_list_sessions(self):
        """Let owners/admins discover orphan handoffs and copy revocation IDs."""
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        team_id=self.cloud_fields["team_id"].get().strip()

        def show(items):
            popup=tk.Toplevel(self.root)
            popup.title("Encrypted team archives (owner/admin)")
            popup.geometry("880x410")
            popup.transient(self.root)
            columns=("uuid","state","documents","bytes","uploaders")
            table=ttk.Treeview(popup,columns=columns,show="headings",selectmode="browse")
            for field,heading,width in (
                ("uuid","Archive UUID",315),("state","State",90),
                ("documents","Documents",90),("bytes","Stored bytes",110),
                ("uploaders","Uploaders",220)
            ):
                table.heading(field,text=heading)
                table.column(field,width=width,stretch=(field=="uploaders"))
            table.pack(fill="both",expand=True,padx=8,pady=8)
            for item in items:
                table.insert("", "end",values=(
                    item["session_id"],
                    "Complete" if item["has_manifest"] else "Partial",
                    item["documents"],item["stored_bytes"],
                    ", ".join(item["uploaders"]) or "Legacy / unknown"
                ))
            def copy_uuid():
                selected=table.selection()
                if not selected:
                    return
                ident=table.item(selected[0],"values")[0]
                self.root.clipboard_clear()
                self.root.clipboard_append(ident)
                self.cloud_status.set("Archive UUID copied for download or revocation")
            ttk.Button(popup,text="Copy selected archive UUID",
                       command=copy_uuid).pack(anchor="w",padx=8,pady=(0,8))
            self.cloud_status.set(f"Admin archive listing: {len(items)} handoff IDs")

        self._cloud_action(lambda:self.cloud.list_sessions(team_id),show)

    def cloud_revoke_session(self):
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        ident=simpledialog.askstring("Revoke published encrypted session",
                 "Paste the archived handoff UUID to revoke:",parent=self.root)
        if not ident:
            return
        team_id=self.cloud_fields["team_id"].get().strip()
        if not messagebox.askyesno("PERMANENT encrypted archive revocation",
                "Only a team OWNER or ADMIN can revoke this encrypted archive.\n\n"
                "The Hub will permanently remove its encrypted parts and "
                "manifest and refuse publishing under this UUID again.\n"
                "This action cannot be undone.\n\n"
                "IMPORTANT: copies previously downloaded by other members "
                "CANNOT be recovered or deleted remotely. Continue?",
                parent=self.root):
            return
        def done(result):
            deleted=result["deleted_documents"]
            self.cloud_status.set(
                f"Archive revoked on hub; {deleted} encrypted documents removed")
            messagebox.showinfo("Hub archive revoked",
                f"The Hub deleted {deleted} encrypted documents and blocked "
                "this handoff ID from being reused.\n\n"
                "Previously downloaded files are NOT revoked.",
                parent=self.root)
        self._cloud_action(lambda:self.cloud.revoke_session(team_id,ident),done)

    def cloud_register(self):
        values={k:v.get() for k,v in self.cloud_fields.items()}
        def task():
            return CloudClient(values["url"]).register(values["username"],values["password"])
        self._cloud_action(task,lambda _:self.cloud_status.set("User registered; log in next"))

    def cloud_login(self):
        values={k:v.get() for k,v in self.cloud_fields.items()}
        def task():
            client=CloudClient(values["url"])
            client.login(values["username"],values["password"])
            return client
        def done(client):
            self.cloud=client
            self.cloud_revision={"profiles":0,"workflows":0}
            # A new sign-in is not proof the same principal owns old baselines.
            # Require a newly approved pull before any subsequent merge.
            self.cloud_bases.clear()
            self.cloud_fields["password"].set("")
            self.cloud_status.set("Authenticated · token kept in memory")
        self._cloud_action(task,done)

    def cloud_create_team(self):
        if not self.cloud:return messagebox.showinfo("Team sync","Log in first")
        self._cloud_action(lambda:self.cloud.create_team("Autumn team"),
            lambda ident:(self.cloud_fields["team_id"].set(ident),self.cloud_status.set("Team created: "+ident)))

    def cloud_invite(self):
        if not self.cloud:return messagebox.showinfo("Team sync","Log in first")
        username=simpledialog.askstring("Add team member","Existing username",parent=self.root)
        if not username:return
        role=simpledialog.askstring("Team role","viewer, editor or admin",parent=self.root)
        if role not in {"viewer","editor","admin"}:return
        team_id=self.cloud_fields["team_id"].get()
        self._cloud_action(lambda:self.cloud.set_member(team_id,username,role),
                           lambda _:self.cloud_status.set(f"Added {username} as {role}"))

    def cloud_sync(self,name,direction):
        from copy import deepcopy
        from .cloud_merge import merge_cloud_documents
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        client=self.cloud
        team_id=self.cloud_fields["team_id"].get().strip()
        passphrase=self.cloud_fields["passphrase"].get()
        if len(passphrase)<12:
            return messagebox.showerror("Sync","Use a passphrase of at least 12 characters",parent=self.root)
        scope=(client.url,team_id,name)
        if direction=="push":
            try:
                # Profile catalog snapshots can wait on SQLite; take them
                # on the sync worker rather than freezing the Tk thread.
                doc=(None if name=="profiles"
                     else {"format":"AutumnGenLogin/workflow-1",
                           "workflow":self.current_steps()})
            except Exception as exc:
                return messagebox.showerror("Sync",type(exc).__name__,parent=self.root)
            if not messagebox.askyesno(
                "Encrypted sync","Review the local document before upload. "
                "Server changes will be checked and never silently overwritten. Continue?",
                parent=self.root
            ):
                return
            baseline=self.cloud_bases.get(scope)
            expected_rev,base_doc=(baseline if baseline else (None,None))
            def inspect():
                local_doc=safe_profile_metadata(self.store) if name=="profiles" else doc
                remote_rev,remote_doc=client.pull(team_id,name,passphrase)
                if expected_rev is not None and (
                    remote_rev < expected_rev or
                    (remote_rev==expected_rev and remote_doc!=base_doc)
                ):
                    return {"conflicts":("remote-revision-regressed",)}
                merged,conflicts=merge_cloud_documents(
                    name,base_doc,local_doc,remote_doc)
                if conflicts:
                    return {"conflicts":conflicts}
                return {"revision":remote_rev,"remote":remote_doc,
                        "merged":merged,"local":local_doc,
                        "needs_review":remote_doc is not None and
                                        remote_doc!=base_doc}
            def inspected(state):
                if state.get("conflicts"):
                    self.cloud_status.set("Conflict: no upload; review remote document first")
                    messagebox.showwarning(
                        "Cloud revision conflict",
                        f"Upload blocked: {len(state['conflicts'])} conflicting location(s). "
                        "Pull and inspect the remote revision before resolving; "
                        "no data was overwritten.",
                        parent=self.root)
                    return
                merged=state["merged"]
                if state["remote"]==merged:
                    self.cloud_status.set(
                        "Remote revision already contains the proposed document. "
                        "Pull to update local data.")
                    return
                if state["needs_review"] and not messagebox.askyesno(
                    "Review three-way merge",
                    "The server changed since your last approved pull. "
                    "A structural three-way merge found no overlapping conflicts. "
                    "Upload the merged metadata now? "
                    "Afterward, pull the merged result to update your local copy.",
                    parent=self.root
                ):
                    self.cloud_status.set("Merge cancelled: nothing uploaded")
                    return
                def submit():
                    # A concurrent local edit after the preview also must not
                    # publish an obsolete profile snapshot under user consent.
                    if name=="profiles" and safe_profile_metadata(self.store)!=state["local"]:
                        raise ValueError("Local profiles changed since upload preview; review again")
                    # Server-side optimistic CAS protects against another
                    # writer racing between preview and this upload.
                    return client.push(team_id,name,state["revision"],merged,passphrase)
                def submitted(revision):
                    if state["needs_review"]:
                        self.cloud_bases.pop(scope,None)
                        self.cloud_status.set(
                            f"Merge uploaded at revision {revision}. Pull before next push.")
                    else:
                        self.cloud_bases[scope]=(revision,deepcopy(merged))
                        self.cloud_status.set(f"Uploaded {name} revision {revision}")
                self._cloud_action(submit,submitted)
            self._cloud_action(inspect,inspected)
        else:
            # Capture the baseline on the Tk owner thread, then perform ALL
            # network, SQLite and merge computation in the background.
            prior=deepcopy(self.cloud_bases.get(scope))
            def task():
                revision,doc=client.pull(team_id,name,passphrase)
                state={"revision":revision,"doc":doc}
                if not doc or name!="profiles":
                    return state
                from .cloud_merge import prepare_cloud_profile_pull
                if prior is not None and (revision<prior[0] or
                        (revision==prior[0] and doc!=prior[1])):
                    return {**state,"conflicts":("remote-revision-regressed",)}
                local_doc=safe_profile_metadata(self.store)
                merged,conflicts=prepare_cloud_profile_pull(
                    local_doc,doc,prior[1] if prior else None)
                state["conflicts"]=conflicts
                if conflicts:
                    return state
                before={item["id"]:item for item in local_doc["profiles"]}
                changes=[item for item in merged["profiles"]
                         if before.get(item["id"])!=item]
                state["expected_local"]=local_doc
                state["pending"]={"format":merged["format"],"profiles":changes}
                return state

            def done(state):
                # Discard replies from a login or team no longer displayed.
                if (self.cloud is not client or
                        self.cloud_fields["team_id"].get().strip()!=team_id or
                        self.cloud_bases.get(scope)!=prior):
                    self.cloud_status.set("Cloud context changed; repeat the Pull review")
                    return
                revision,doc=state["revision"],state["doc"]
                if not doc:
                    return self.cloud_status.set("No remote document")
                if state.get("conflicts"):
                    self.cloud_status.set(
                        f"Pull blocked: {len(state['conflicts'])} local/remote metadata conflict(s)")
                    return messagebox.showwarning(
                        "Cloud pull needs conflict resolution",
                        f"Found {len(state['conflicts'])} overlapping or unverified field(s). "
                        "No local profiles were modified. Review and reconcile "
                        "the same profile ID on both sides before retrying.",
                        parent=self.root)
                if name=="profiles":
                    pending=state["pending"]
                    summary=(f"Apply {len(pending['profiles'])} new/updated safe "
                             "profile metadata record(s)? Local-only records "
                             "and proxy/vault credentials will be preserved. "
                             "Conflicting local edits were not overwritten.")
                else:
                    summary=(f"Import encrypted {name} revision {revision} into local data? "
                             "This establishes a baseline for future conflict detection.")
                if not messagebox.askyesno("Cloud preview",summary,parent=self.root):
                    return

                def accepted():
                    if self.cloud is not client or self.cloud_bases.get(scope)!=prior:
                        self.cloud_status.set("Cloud context changed; repeat Pull")
                        return
                    self.cloud_bases[scope]=(revision,deepcopy(doc))
                    self.cloud_revision[name]=revision

                if name=="profiles":
                    from .team_sync import merge_safe_profiles
                    def apply():
                        return merge_safe_profiles(
                            self.store,state["pending"],
                            active=self.manager.active,
                            expected_local=state["expected_local"])
                    def applied(count):
                        self.refresh()
                        self.cloud_status.set(
                            f"Reconciled {count} changed profile metadata rows; "
                            "local-only profiles preserved")
                        accepted()
                    # SQLite BEGIN IMMEDIATE and save now execute on a
                    # thread-affine worker, never inside a Tk callback.
                    self._cloud_action(apply,applied)
                else:
                    try:
                        if doc.get("format")!="AutumnGenLogin/workflow-1":
                            raise ValueError("Wrong workflow format")
                        flow=doc["workflow"]
                        if isinstance(flow,dict):
                            self.graph_builder.set_graph(flow)
                            self.flow_tabs.select(2)
                        else:
                            self.builder.set_steps(validated_steps(flow))
                            self.flow_tabs.select(0)
                        self.cloud_status.set("Downloaded workflow")
                        accepted()
                    except Exception as exc:
                        self.cloud_status.set("Pull failed: no baseline was updated")
                        messagebox.showerror("Team sync",type(exc).__name__,parent=self.root)
            self._cloud_action(task,done)

