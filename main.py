import os
import asyncio
import discord
from discord.ext import commands
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn
from upstash_redis.asyncio import Redis
import re

# Inisialisasi Redis (otomatis ambil dari ENV)
redis = Redis.from_env()

TOKENS = os.getenv("DISCORD_TOKENS", "").split(",")
TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID", 0))
app = FastAPI()

# Global State
current_tumbal_idx = 0
logs = []
giveaway_registry = {} # {msg_id: {"buttons": [], "winner": None}}

def add_log(msg):
    logs.insert(0, msg)
    if len(logs) > 20: logs.pop()

class GiveawayBot(commands.Bot):
    def __init__(self, index, token):
        super().__init__(command_prefix="!", self_bot=True)
        self.index = index
        self.token = token

    async def on_ready(self):
        add_log(f"Bot {self.index} Ready: {self.user.name}")

    async def on_message(self, message):
        global current_tumbal_idx
        if not message.guild or message.guild.id != TARGET_GUILD_ID: return
        
        # EXPLORER LOGIC (Hanya Tumbal)
        if self.index == current_tumbal_idx:
            if message.author.name == "LionNSEX":
                await self.explore_ga(message)

        # SWARM LOGIC (Semua Akun)
        if message.author.name == "LionNSEX":
            await self.check_win(message)

    async def explore_ga(self, message):
        if message.id in giveaway_registry: return
        
        buttons = [c for r in message.components for c in r.children if c.type == discord.ComponentType.button]
        if buttons:
            giveaway_registry[message.id] = {"buttons": buttons, "tried": []}
            add_log(f"Tumbal menemukan GA! Tombol: {len(buttons)}")
            await buttons[0].click() # Tes tombol pertama

    async def check_win(self, message):
        content = (message.content + " " + " ".join([e.description or "" for e in message.embeds])).lower()
        
        # Cek apakah sudah klaim
        if await redis.sismember("claimed_ids", message.id): return

        if "you got:" in content or "you won" in content:
            # Klaim Berhasil!
            await redis.sadd("claimed_ids", message.id)
            add_log(f"Bot {self.index} Berhasil menang!")
            
        elif "already" in content:
            # Zonk/Already - Switch tombol
            msg_id = message.reference.message_id if message.reference else None
            if msg_id and msg_id in giveaway_registry:
                # Logika Barbar: Jika satu tombol zonk, semua akun hindari tombol ini
                pass

    async def swarm_click(self, button):
        try:
            await button.click()
        except Exception as e:
            add_log(f"Error click: {e}")

# Inisialisasi instance
bots = [GiveawayBot(i, t) for i, t in enumerate(TOKENS) if t]

@app.get("/")
async def home():
    options = "".join([f"<option value='{i}' {'selected' if i == current_tumbal_idx else ''}>Akun {i}</option>" for i in range(len(bots))])
    return HTMLResponse(f"<html><body><h1>Swarm Panel</h1><select onchange='fetch(\"/set-tumbal?idx=\"+this.value)'>{options}</select><pre>{chr(10).join(logs)}</pre></body></html>")

@app.get("/set-tumbal")
async def set_tumbal(idx: int):
    global current_tumbal_idx
    current_tumbal_idx = idx
    return {"status": "ok"}

async def main():
    await asyncio.gather(*[bot.start(bot.token) for bot in bots], uvicorn.run(app, host="0.0.0.0", port=8000))

if __name__ == "__main__":
    asyncio.run(main())
