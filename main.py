import os
import asyncio
import discord
import uvicorn
from discord.ext import commands
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from upstash_redis.asyncio import Redis

# 1. SETUP ENV & REDIS
if "UPSTASH_REDIS_REST_URL" in os.environ:
    redis = Redis.from_env()
else:
    redis = None
    print("WARNING: Redis tidak terdeteksi!")

TOKENS = os.getenv("DISCORD_TOKENS", "").split(",")
TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID", 0) or 0)
PORT = int(os.getenv("PORT", 8000))

app = FastAPI()
logs = []
current_tumbal_idx = 0
giveaway_registry = {} 

def add_log(msg):
    print(msg)
    logs.insert(0, msg)
    if len(logs) > 50: logs.pop()

class GiveawayBot(commands.Bot):
    def __init__(self, index, token):
        # discord.py-self tidak butuh deklarasi intents manual
        super().__init__(command_prefix="!", self_bot=True)
        self.index = index
        self.token = token

    async def on_ready(self):
        add_log(f"Akun {self.index} Logged in: {self.user.name}")

    async def on_message(self, message):
        if not message.guild or message.guild.id != TARGET_GUILD_ID: return
        
        # LOGIC EXPLORER (HANYA TUMBAL)
        if self.index == current_tumbal_idx and message.author.name == "LionNSEX":
            await self.explore_ga(message)

    async def explore_ga(self, message):
        if message.id in giveaway_registry: return
        
        # Cari tombol
        buttons = [c for r in message.components for c in r.children if c.type == discord.ComponentType.button]
        if buttons:
            giveaway_registry[message.id] = {"buttons": buttons}
            add_log(f"Tumbal menemukan GA! Klik tombol...")
            try:
                await buttons[0].click()
                await asyncio.sleep(2.5) # Tunggu bot balas
                
                # Capture result
                result = await self.capture_result(message.channel)
                add_log(f"RESULT: {message.embeds[0].title if message.embeds else 'GA'} > {result}")
            except Exception as e:
                add_log(f"Error Explorer: {e}")

    async def capture_result(self, channel):
        async for msg in channel.history(limit=5):
            if msg.author.name == "LionNSEX":
                raw = (msg.content + " " + " ".join([e.description or "" for e in msg.embeds])).strip()
                # Bersihkan pesan
                clean = raw.replace("You already picked!", "").replace("You won!", "").strip()
                return clean[:60]
        return "No response"

# INIT BOTS
bots = [GiveawayBot(i, t) for i, t in enumerate(TOKENS) if t]

# 2. WEB UI & API
@app.get("/", response_class=HTMLResponse)
async def home():
    options = "".join([f"<option value='{i}' {'selected' if i == current_tumbal_idx else ''}>Akun {i}</option>" for i in range(len(bots))])
    return f"<html><body><h1>Swarm Panel</h1><select onchange='fetch(\"/set-tumbal?idx=\"+this.value)'>{options}</select><pre>{chr(10).join(logs)}</pre></body></html>"

@app.get("/set-tumbal")
async def set_tumbal(idx: int):
    global current_tumbal_idx
    current_tumbal_idx = idx
    add_log(f"Tumbal diganti ke Akun {idx}")
    return {"status": "ok"}

# 3. RUNNER
async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    
    # Jalankan bot dan server secara bersamaan
    tasks = [bot.start(bot.token) for bot in bots]
    tasks.append(server.serve())
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
