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
                # Embedメッセージの作成（正常動作時）
                embed = discord.Embed(
                    title="Roulette Start!",
                    description=f"Bet Amount: {bet_amount} coins\nBet Type: {bet_type}",
                    color=discord.Color.blue()
                )
                await message.channel.send(embed=embed)
            else:
                # Embedメッセージの作成（エラー時）
                embed = discord.Embed(
                    title="Error",
                    description="Please enter a valid bet amount.",
                    color=discord.Color.red()
                )
                await message.channel.send(embed=embed)
        else:
            # Embedメッセージの作成（コマンド形式が無効な場合）
            embed = discord.Embed(
                title="Error",
                description="Invalid command. Usage: /roulette <amount> <even/odd>",
                color=discord.Color.red()
            )

        await message.channel.send(embed=embed)

server_thread()
client.run(TOKEN)