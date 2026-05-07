# Placeholder Generator

Turns any PDF module into a 2x placeholder PNG. Includes an interactive editor to drag, resize, add, and delete boxes before exporting.

## Deploy to Railway

1. Push this folder to a GitHub repo (instructions below)
2. Go to railway.app and sign in with GitHub
3. Click New Project → Deploy from GitHub repo
4. Select your repo — Railway auto-detects everything
5. Once deployed: Settings → Networking → Generate Domain
6. Share that URL with your team

### Push to GitHub (one time)
```bash
cd ~/Downloads/placeholder-tool
git init
git add .
git commit -m "Initial commit"
# Create a new repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/placeholder-tool.git
git push -u origin main
```

## Run locally

One-time setup (Mac):
```bash
brew install python poppler
pip3 install -r requirements.txt
```

Start the server:
```bash
python3 server.py
```

Open http://localhost:7765
