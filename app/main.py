import discord
import os
import dotenv
from server import server_thread
dotenv.load_dotenv()

TOKEN = os.environ.get("TOKEN")
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
client = discord.Client(intents=intents)

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith('/roulette'):
        parts = message.content.split()
        if len(parts) == 3 and parts[1].isdigit() and parts[2] in ['even', 'odd']:
            bet_amount = int(parts[1])
            bet_type = parts[2]
            if bet_amount > 0:
                await message.channel.send(f"Roulette started with a bet of {bet_amount} coins on {bet_type}!")
            else:
                await message.channel.send("Please enter a valid bet amount.")
        else:
            await message.channel.send("Invalid command. Usage: /roulette <bet_amount> <even/odd>")

server_thread()
client.run(TOKEN)