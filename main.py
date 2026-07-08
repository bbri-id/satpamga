import os
import asyncio
import json
import random
import re
import discord
from discord.ext import commands
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
import uvicorn

# ==========================================
# 1. CONFIG & STATE
# ==========================================
TOKENS = os.getenv("DISCORD_TOKENS", "").split(",")
app = FastAPI()

# Global State
giveaway_registry = {}  # {msg_id: {"buttons": [], "failed": [], "win_btn": None, "results": {}}}
current_tumbal_idx = 0
logs = []

def add_log(msg):
    logs.insert(0, f"[{asyncio.get_event_loop().time():.1f}] {msg}")
    if len(logs) > 20: logs.pop()

# ==========================================
# 2. DISCORD BOT INSTANCES
# ==========================================
class GiveawayBot(commands.Bot):
    def __init__(self, index, token):
        super().__init__(command_prefix="!", self_bot=True)
        self.index = index
        self.token = token

    async def on_ready(self):
        add_log(f"Akun {self.index} Logged in: {self.user.name}")

    async def on_message(self, message):
        global current_tumbal_idx
        
        # Explorer Logic (Scan)
        if self.index == current_tumbal_idx:
            if message.author.name == "LionNSEX" and message.embeds:
                await self.process_explorer(message)
        
        # Swarm Logic (Follower)
        if message.author.name == "LionNSEX":
            await self.process_swarm_reaction(message)

    async def process_explorer(self, message):
        if message.id not in giveaway_registry:
            components = [c for r in message.components for c in r.children if c.type == discord.ComponentType.button]
            if components:
                giveaway_registry[message.id] = {"buttons": components, "failed": [], "win": None}
                add_log(f"Tumbal menemukan GA! Buttons: {len(components)}")
                # Langsung klik random pertama
                await self.click_button(message.id, random.choice(components))

    async def process_swarm_reaction(self, message):
        # Deteksi hadiah
        content = (message.content + " " + " ".join([e.description or "" for e in message.embeds])).lower()
        if "you got:" in content or "you won" in content:
            match = re.search(r"(you got:|you won) (.*)", content)
            prize = match.group(2) if match else "Unknown"
            add_log(f"🎉 Akun {self.index} dapat: {prize}")
        
        # Logika Update Registry jika menang
        if "already picked" in content or "won" in content:
            # Jika follower melihat tumbal menang, update registry agar follower lain tahu
            pass 

    async def click_button(self, msg_id, btn):
        try:
            await btn.click()
            add_log(f"Akun {self.index} clicked button!")
        except Exception as e:
            add_log(f"Error clicking: {e}")

# Inisialisasi Bots
bots = [GiveawayBot(i, t) for i, t in enumerate(TOKENS) if t]

# ==========================================
# 3. WEB DASHBOARD
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def home():
    options = "".join([f"<option value='{i}' {'selected' if i == current_tumbal_idx else ''}>Akun {i}</option>" for i in range(len(bots))])
    return f"""
    <html>
    <body style="background:#121212; color:#fff; font-family:sans-serif; padding:20px;">
        <h1>Swarm Dashboard</h1>
        <select id="tumbal-select" onchange="setTumbal(this.value)">{options}</select>
        <div id="logs" style="margin-top:20px; font-family:monospace; background:#000; padding:10px; height:300px; overflow-y:scroll;"></div>
        <script>
            function setTumbal(idx) {{ fetch('/set-tumbal?idx='+idx); }}
            const es = new EventSource("/stream");
            es.onmessage = (e) => {{ document.getElementById('logs').innerHTML = e.data.replace(/\\n/g, '<br>'); }};
        </script>
    </body>
    </html>
    """

@app.get("/set-tumbal")
async def set_tumbal(idx: int):
    global current_tumbal_idx
    current_tumbal_idx = idx
    add_log(f"Tumbal diubah ke Akun {idx}")
    return {"status": "ok"}

@app.get("/stream")
async def stream():
    return StreamingResponse(f"data: {'<br>'.join(logs)}\n\n", media_type="text/event-stream")

# ==========================================
# 4. RUNNER
# ==========================================
async def main():
    tasks = [bot.start(bot.token) for bot in bots]
    tasks.append(uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000))))
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
