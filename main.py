import os
import asyncio
import discord
import uvicorn
from discord.ext import commands
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from upstash_redis.asyncio import Redis

# 1. SETUP
REDIS = Redis.from_env()
TOKENS = os.getenv("DISCORD_TOKENS", "").split(",")
TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID", 0) or 0)
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID", 0) or 0)
PORT = int(os.getenv("PORT", 8000))

app = FastAPI()
logs = []
current_tumbal_idx = 0

def add_log(msg):
    print(msg)
    logs.insert(0, f"[{msg}]")
    if len(logs) > 100: logs.pop()

class GiveawayBot(commands.Bot):
    def __init__(self, index, token):
        super().__init__(command_prefix="!", self_bot=True)
        self.index = index
        self.token = token

    async def on_ready(self):
        add_log(f"Akun {self.index} ({self.user.name}) Ready")

    async def full_scan(self):
        """Scan seluruh history channel & simpan ke Redis agar persisten"""
        channel = self.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            add_log("Error: Channel tidak ditemukan!")
            return

        add_log(f"Mulai Full Scan di {channel.name}...")
        count = 0
        # limit=None mengambil seluruh history server
        async for msg in channel.history(limit=None):
            # Cek di Redis apakah ID ini sudah pernah diproses
            is_processed = await REDIS.sismember("claimed_gas", msg.id)
            if is_processed:
                continue
            
            buttons = [c for r in msg.components for c in r.children if c.type == discord.ComponentType.button]
            if buttons:
                try:
                    await buttons[0].click()
                    await REDIS.sadd("claimed_gas", msg.id) # Simpan ke Redis
                    add_log(f"Berhasil claim GA lama: {msg.id}")
                    count += 1
                    await asyncio.sleep(2) # Anti-rate limit
                except Exception as e:
                    add_log(f"Err claim GA {msg.id}: {e}")
        
        add_log(f"Full Scan selesai. Total claim baru: {count}")

    async def on_message(self, message):
        if not message.guild or message.guild.id != TARGET_GUILD_ID: return
        
        # Real-time GA Detection
        is_processed = await REDIS.sismember("claimed_gas", message.id)
        if not is_processed and message.author.name == "LionNSEX":
            buttons = [c for r in message.components for c in r.children if c.type == discord.ComponentType.button]
            if buttons:
                try:
                    await buttons[0].click()
                    await REDIS.sadd("claimed_gas", message.id)
                    add_log("Real-time GA claimed.")
                except Exception as e:
                    add_log(f"Err: {e}")

# INIT
bots = [GiveawayBot(i, t) for i, t in enumerate(TOKENS) if t]

# 2. UI
@app.get("/", response_class=HTMLResponse)
async def home():
    options = "".join([f"<option value='{i}' {'selected' if i == current_tumbal_idx else ''}>Akun {i}</option>" for i in range(len(bots))])
    return f"""
    <html class="dark"><body class="bg-gray-900 text-white p-8 font-sans">
        <h1 class="text-2xl font-bold mb-4 text-indigo-400">Swarm Persistent Dashboard</h1>
        <div class="bg-gray-800 p-4 rounded border border-gray-700">
            <button onclick="fetch('/scan')" class="w-full bg-red-600 hover:bg-red-500 p-3 rounded font-bold text-lg animate-pulse">RUN FULL SERVER SCAN</button>
            <pre id="logs" class="mt-4 bg-black p-4 text-green-400 text-xs h-64 overflow-y-auto">{chr(10).join(logs)}</pre>
        </div>
    </body></html>
    """

@app.get("/scan")
async def trigger_scan():
    asyncio.create_task(bots[current_tumbal_idx].full_scan())
    return {"status": "scanning"}

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    tasks = [bot.start(bot.token) for bot in bots]
    tasks.append(server.serve())
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
