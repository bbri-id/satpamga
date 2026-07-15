import os
import asyncio
import discord
import uvicorn
from discord.ext import commands
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from upstash_redis.asyncio import Redis

# --- SETUP ---
REDIS = Redis.from_env()
TOKENS = os.getenv("DISCORD_TOKENS", "").split(",")
TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID", 0) or 0)
PORT = int(os.getenv("PORT", 8000))

app = FastAPI()
logs = ["System Initialized..."]
current_tumbal_idx = 0

def add_log(msg):
    print(msg)
    logs.insert(0, f"> {msg}")
    if len(logs) > 100: logs.pop()

class GiveawayBot(commands.Bot):
    def __init__(self, index, token):
        super().__init__(command_prefix="!", self_bot=True)
        self.index = index
        self.token = token

    async def on_ready(self):
        add_log(f"--- AKUN {self.index} ({self.user.name}) READY ---")
        guild = self.get_guild(TARGET_GUILD_ID)
        if guild:
            # Filter hanya TextChannel untuk log
            text_channels = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
            add_log(f"Bot mendeteksi {len(text_channels)} Text Channel. Berikut daftarnya:")
            for c in text_channels:
                add_log(f"  -> {c.name} | Tipe: text")
        else:
            add_log(f"Error: Bot tidak menemukan server dengan ID {TARGET_GUILD_ID}.")

    async def full_scan(self):
        guild = self.get_guild(TARGET_GUILD_ID)
        if not guild:
            add_log("Error: Bot tidak mendeteksi server!")
            return

        add_log(f"Scanning server {guild.name}...")
        # Hanya ambil text channels
        text_channels = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
        
        add_log(f"Total channel teks yang akan di-scan: {len(text_channels)}")
        total_claimed = 0

        for i, channel in enumerate(text_channels):
            add_log(f"Scanning #{channel.name} ({i+1}/{len(text_channels)})")
            
            try:
                # Scan 500 pesan terakhir
                async for msg in channel.history(limit=500): 
                    if await REDIS.sismember("claimed_gas", msg.id): continue
                    
                    buttons = [c for r in msg.components for c in r.children if c.type == discord.ComponentType.button]
                    if buttons:
                        try:
                            await buttons[0].click()
                            await REDIS.sadd("claimed_gas", msg.id)
                            add_log(f"-> Claimed GA di #{channel.name}: {msg.id}")
                            total_claimed += 1
                            await asyncio.sleep(1.5) 
                        except Exception as e:
                            add_log(f"Err click #{channel.name}: {e}")
            except Exception as e:
                add_log(f"Err access #{channel.name}: {e}")
        
        add_log(f"SCAN SELESAI. Total {total_claimed} giveaway berhasil diklaim.")

    async def on_message(self, message):
        if not message.guild or message.guild.id != TARGET_GUILD_ID: return
        if await REDIS.sismember("claimed_gas", message.id): return
        
        if message.author.name == "LionNSEX":
            buttons = [c for r in message.components for c in r.children if c.type == discord.ComponentType.button]
            if buttons:
                try:
                    await buttons[0].click()
                    await REDIS.sadd("claimed_gas", message.id)
                    add_log(f"Real-time GA claimed in #{message.channel.name}")
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
            body {{ background: #121212; color: #e0e0e0; font-family: monospace; margin: 20px; }}
            .card {{ background: #1e1e1e; padding: 20px; border-radius: 8px; border: 1px solid #333; }}
            button {{ background: #4caf50; color: white; border: none; padding: 10px 20px; cursor: pointer; border-radius: 4px; font-weight: bold; }}
            select {{ background: #333; color: white; padding: 8px; border-radius: 4px; width: 100%; margin-bottom: 20px; }}
            pre {{ background: #000; color: #00ff00; padding: 15px; height: 500px; overflow-y: auto; font-size: 12px; border: 1px solid #333; }}
        </style>
    </head>
    <body>
        <h2>Swarm Global Scanner (Clean)</h2>
        <div class="card">
            <select onchange="fetch('/set-tumbal?idx='+this.value)">{options}</select>
            <button id="scanBtn" onclick="runScan()">RUN GLOBAL SCAN TEXT CHANNELS</button>
            <h3 style="margin-top:20px;">Real-time Activity:</h3>
            <pre id="log-box"></pre>
        </div>
        <script>
            function runScan() {{
                document.getElementById('scanBtn').innerText = "Scanning...";
                fetch('/scan');
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
