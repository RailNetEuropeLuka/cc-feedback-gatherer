# Deploying the Feedback Gatherer to Streamlit Community Cloud (free)

This gives you a public link like `https://your-app.streamlit.app` that anyone can
open in a browser — no install needed for testers.

> 🔒 **Safety:** the real consultation archive (`2025 CCs Guidelines review/`) is
> excluded by `.gitignore`, so it is **never** uploaded to GitHub. The deployed app
> runs in **demo mode** (no respondent registry, no personal data). Testers only see
> what *they* upload, and uploads are processed in memory and never stored.

---

## What gets published
Only the tool + synthetic samples:
```
feedback_gatherer/      app.py, engine.py, extractors/, config.yaml, …
feedback_gatherer/samples/   dummy fictional feedback files for testers
requirements.txt        (repo root — Streamlit Cloud reads this)
.streamlit/config.toml
.gitignore              (keeps the real data out)
```

## Step 1 — Put the code on GitHub
1. Create a free account at <https://github.com> if you don't have one.
2. Create a **new repository** (e.g. `cc-feedback-gatherer`). It can be **public**
   (fine — no real data is included) or private.
3. Push this project. From a terminal in the project folder:
   ```bash
   git init
   git add .
   git status            # CONFIRM "2025 CCs Guidelines review/" is NOT listed
   git commit -m "Feedback Gatherer – deployable app + samples"
   git branch -M main
   git remote add origin https://github.com/<your-username>/cc-feedback-gatherer.git
   git push -u origin main
   ```
   *(An initial commit has already been created for you locally — you may only need
   the `remote add` + `push` steps. Always re-check `git status`/the GitHub file list
   to be sure the archive isn't there.)*

## Step 2 — Deploy on Streamlit Cloud
1. Go to <https://share.streamlit.io> and sign in **with GitHub**.
2. Click **Create app → Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `<your-username>/cc-feedback-gatherer`
   - **Branch:** `main`
   - **Main file path:** `feedback_gatherer/app.py`
4. Click **Deploy**. First build takes a few minutes (it installs `requirements.txt`).
5. You get a URL like `https://cc-feedback-gatherer.streamlit.app` — share it.

## Step 3 — (Optional) restrict who can open it
On the free tier you can limit viewers to specific e-mail addresses:
- App → **Settings → Sharing** → turn off "anyone with the link", add allowed e-mails.
Testers then sign in with Google to view.

---

## Good to know
- **Sleeping:** a free app sleeps after inactivity; the next visitor waits ~30 s for
  it to wake. Normal for the free tier.
- **Updating:** push to GitHub → the app redeploys automatically.
- **Resources:** ~1 GB RAM, plenty for this tool; upload size capped at 50 MB.
- **Real stakeholder data:** for processing *actual* consultation feedback (not a
  demo), host internally (RNE Azure / intranet) instead — see the team for hosting.
