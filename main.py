import os
import asyncio
import discord
import uvicorn
from discord.ext import commands
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from upstash_redis.asyncio import Redis

# --- SETUP ---
# Pastikan ENVIRONMENT VARIABLE di Render sudah diisi dengan benar:
# DISCORD_TOKENS, TARGET_GUILD_ID, TARGET_CHANNEL_ID, UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN
REDIS = Redis.from_env()
TOKENS = os.getenv("DISCORD_TOKENS", "").split(",")
TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID", 0) or 0)
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID", 0) or 0)
PORT = int(os.getenv("PORT", 8000))

app = FastAPI()
logs = ["System Initialized..."]
current_tumbal_idx = 0

def add_log(msg):
    print(msg)
    logs.insert(0, f"> {msg}")
    if len(logs) > 50: logs.pop()

class GiveawayBot(commands.Bot):
    def __init__(self, index, token):
        # Menggunakan discord.py-self (self_bot=True)
        super().__init__(command_prefix="!", self_bot=True)
        self.index = index
        self.token = token

    async def on_ready(self):
        add_log(f"Akun {self.index} ({self.user.name}) Ready")

    async def full_scan(self):
        """Fitur Scan Full History menggunakan fetch_channel"""
        try:
            # fetch_channel memaksa bot mengambil data langsung dari API, bukan cache
            channel = await self.fetch_channel(TARGET_CHANNEL_ID)
        except Exception as e:
            add_log(f"Error: Gagal fetch channel {TARGET_CHANNEL_ID}: {e}")
            return

        add_log(f"--- STARTING FULL SCAN: {channel.name} ---")
        count = 0
        async for msg in channel.history(limit=None):
            # Cek Redis apakah ID sudah diproses
            if await REDIS.sismember("claimed_gas", msg.id): continue
            
            buttons = [c for r in msg.components for c in r.children if c.type == discord.ComponentType.button]
            if buttons:
                try:
                    await buttons[0].click()
                    await REDIS.sadd("claimed_gas", msg.id)
                    add_log(f"Claimed GA: {msg.id}")
                    count += 1
                    await asyncio.sleep(2) # Anti-rate limit
                except Exception as e:
                    add_log(f"Err {msg.id}: {e}")
        
        add_log(f"SCAN SELESAI. Total Claim: {count}")

    async def on_message(self, message):
        # Real-time listener
        if not message.guild or message.guild.id != TARGET_GUILD_ID: return
        
        if await REDIS.sismember("claimed_gas", message.id): return
        
        if message.author.name == "LionNSEX":
            buttons = [c for r in message.components for c in r.children if c.type == discord.ComponentType.button]
            if buttons:
                try:
                    await buttons[0].click()
                    await REDIS.sadd("claimed_gas", message.id)
                    add_log(f"Real-time GA claimed: {message.id}")
                except Exception as e:
                    add_log(f"Err Real-time: {e}")

bots = [GiveawayBot(i, t) for i, t in enumerate(TOKENS) if t]

# --- UI & API ---
@app.get("/get-logs")
async def get_logs():
    return {"logs": logs}

@app.get("/", response_class=HTMLResponse)
async def home():
    options = "".join([f"<option value='{i}' {'selected' if i == current_tumbal_idx else ''}>Akun {i}</option>" for i in range(len(bots))])
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ background: #121212; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; margin: 40px; }}
            .card {{ background: #1e1e1e; padding: 20px; border-radius: 8px; border: 1px solid #333; }}
            button {{ background: #cf6679; color: white; border: none; padding: 10px 20px; cursor: pointer; border-radius: 4px; font-weight: bold; }}
            select {{ background: #333; color: white; padding: 8px; border-radius: 4px; width: 100%; margin-bottom: 20px; }}
            pre {{ background: #000; color: #00ff00; padding: 15px; height: 300px; overflow-y: auto; font-family: monospace; font-size: 12px; }}
        </style>
    </head>
    <body>
        <h1>Swarm Dashboard</h1>
        <div class="card">
            <label>Selected Account:</label>
            <select onchange="fetch('/set-tumbal?idx='+this.value)">{options}</select>
            <button id="scanBtn" onclick="runScan()">RUN FULL SERVER SCAN</button>
            <h3 style="margin-top:20px;">Live Logs:</h3>
            <pre id="log-box"></pre>
        </div>
        <script>
            function runScan() {{
                document.getElementById('scanBtn').innerText = "Scanning...";
                fetch('/scan').then(() => alert("Scan started in background"));
            }}
            setInterval(() => {{
                fetch('/get-logs').then(r => r.json()).then(data => {{
                    document.getElementById('log-box').innerText = data.logs.join('\\n');
                }});
            }}, 1000);
        </script>
    </body>
    </html>
    """

@app.get("/scan")
async def trigger_scan():
    asyncio.create_task(bots[current_tumbal_idx].full_scan())
    return {"status": "scanning"}

@app.get("/set-tumbal")
async def set_tumbal(idx: int):
    global current_tumbal_idx
    current_tumbal_idx = idx
    add_log(f"Switched to Acc {idx}")
    return {"status": "ok"}

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    tasks = [bot.start(bot.token) for bot in bots]
    tasks.append(server.serve())
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
