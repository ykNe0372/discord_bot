import discord
from discord import app_commands
from discord.ext import commands
import os
import random
from dotenv import load_dotenv
from server import server_thread

load_dotenv()

# TOKEN = os.environ.get('TOKEN')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

# ユーザーの所持金を管理する辞書
user_balances = {}

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    # スラッシュコマンドを同期
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # 初期化: 全メンバーに所持金を設定
    for guild in bot.guilds:
        for member in guild.members:
            user_balances[member.id] = 200

# スラッシュコマンド: /balance
@bot.tree.command(name="balance", description="Check your balance or another user's balance.")
@app_commands.describe(user="Select a user to check their balance (optional).")
async def balance(interaction: discord.Interaction, user: discord.Member = None):
    # ユーザーが指定されていない場合は実行者を対象にする
    target_user = user or interaction.user
    user_id = target_user.id

    if user_id in user_balances:
        balance = user_balances[user_id]
        embed = discord.Embed(
            title="Balance",
            description=f"{target_user.name} has {balance} coins.",
            color=discord.Color.green()
        )
        embed.set_author(name=target_user.name, icon_url=target_user.avatar.url)
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(
            title="Error",
            description=f"{target_user.name} does not have a balance yet.",
            color=discord.Color.red()
        )
        embed.set_author(name=target_user.name, icon_url=target_user.avatar.url)
        await interaction.response.send_message(embed=embed)

# スラッシュコマンド: /balance_all
@bot.tree.command(name="balance_all", description="Check the balance of all members in the server.")
async def balance_all(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    # 全メンバーの所持金を取得
    balances = []
    for member in guild.members:
        if not member.bot:  # ボットを除外
            balance = user_balances.get(member.id, 0)
            balances.append((member.name, balance))

    if not balances:
        await interaction.response.send_message("No balances found for members.", ephemeral=True)
        return

    # 名前と所持金を整列
    max_name_length = max(len(name) for name, _ in balances)  # 名前の最大長を取得
    formatted_balances = [f"{name:<{max_name_length}} : {balance} coins" for name, balance in balances]

    # Embedメッセージで出力
    embed = discord.Embed(
        title="All Members' Balances",
        description=f"```\n" + "\n".join(formatted_balances) + "\n```",  # コードブロックで囲む
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=interaction.user.avatar.url)
    await interaction.response.send_message(embed=embed)

# スラッシュコマンド: /roulette
@bot.tree.command(name="roulette", description="Play roulette. Usage: /roulette <amount> <option> <number>")
@app_commands.describe(amount="The amount to bet", option="Choose your bet option", number="Choose a number between 0 and 36 (only for 'Number')")
@app_commands.choices(
    option=[
        app_commands.Choice(name="Even", value="even"),
        app_commands.Choice(name="Odd", value="odd"),
        app_commands.Choice(name="Small (1-12)", value="small"),
        app_commands.Choice(name="Medium (13-24)", value="medium"),
        app_commands.Choice(name="Large (25-36)", value="large"),
        app_commands.Choice(name="First Half (1-18)", value="first"),
        app_commands.Choice(name="Second Half (19-36)", value="second"),
        app_commands.Choice(name="Number", value="number"),
    ]
)
async def roulette(interaction: discord.Interaction, amount: int, option: app_commands.Choice[str], number: int = None):
    # 入力の検証
    if option.value == "number" and (number is None or number < 0 or number > 36):
        await interaction.response.send_message("Please specify a valid number between 0 and 36 after selecting 'Number'.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("Please enter a valid bet amount.", ephemeral=True)
        return

    user_id = interaction.user.id
    if user_id not in user_balances:
        user_balances[user_id] = 0  # 所持金が未設定の場合は0に初期化

    # 賭け金が所持金を超えている場合の警告を追加
    if user_balances[user_id] < amount:
        await interaction.response.send_message(
            f"Warning: You are betting more than your current balance ({user_balances[user_id]} coins). Your balance will go negative if you lose.",
            ephemeral=True
        )

    # Embedメッセージで賭け情報を送信
    embed_description = f"Bet Amount: {amount} coins\nBet Option: {option.name}"
    if option.value == "number":
        embed_description += f"\nChosen Number: {number}"

    embed = discord.Embed(
        title="Roulette Bet",
        description=embed_description,
        color=discord.Color.blue()
    )
    embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url)
    await interaction.response.send_message(embed=embed)

    # 賭けた分を先に減らす
    user_balances[user_id] -= amount

    # ルーレットの結果を計算
    result = random.randint(0, 36)
    result_type = "even" if result % 2 == 0 else "odd"

    # 勝敗判定
    if option.value == "number":
        if result == number:
            user_balances[user_id] += amount * 36
            result_message = f"The roulette landed on {result}.\nYOU WIN! The number matched! You gained {amount * 36} coins.\n\n{interaction.user.name} now have {user_balances[user_id]} coins."
        else:
            result_message = f"The roulette landed on {result}.\nYOU LOSE... The number didn't match. You lost {amount} coins.\n\n{interaction.user.name} now have {user_balances[user_id]} coins."
    elif option.value == "small" and 1 <= result <= 12:
        user_balances[user_id] += amount * 3
        result_message = f"The roulette landed on {result}.\nYOU WIN! The range matched! You gained {amount * 3} coins.\n\n{interaction.user.name} now have {user_balances[user_id]} coins."
    elif option.value == "medium" and 13 <= result <= 24:
        user_balances[user_id] += amount * 3
        result_message = f"The roulette landed on {result}.\nYOU WIN! The range matched! You gained {amount * 3} coins.\n\n{interaction.user.name} now have {user_balances[user_id]} coins."
    elif option.value == "large" and 25 <= result <= 36:
        user_balances[user_id] += amount * 3
        result_message = f"The roulette landed on {result}.\nYOU WIN! The range matched! You gained {amount * 3} coins.\n\n{interaction.user.name} now have {user_balances[user_id]} coins."
    elif option.value == "first" and 1 <= result <= 18:
        user_balances[user_id] += amount * 2
        result_message = f"The roulette landed on {result}.\nYOU WIN! The range matched! You gained {amount * 2} coins.\n\n{interaction.user.name} now have {user_balances[user_id]} coins."
    elif option.value == "second" and 19 <= result <= 36:
        user_balances[user_id] += amount * 2
        result_message = f"The roulette landed on {result}.\nYOU WIN! The range matched! You gained {amount * 2} coins.\n\n{interaction.user.name} now have {user_balances[user_id]} coins."
    elif option.value == "even" and result_type == "even":
        user_balances[user_id] += amount * 2
        result_message = f"The roulette landed on {result} ({result_type}).\nYOU WIN! You gained {amount} coins.\n\n{interaction.user.name} now have {user_balances[user_id]} coins."
    elif option.value == "odd" and result_type == "odd":
        user_balances[user_id] += amount * 2
        result_message = f"The roulette landed on {result} ({result_type}).\nYOU WIN! You gained {amount} coins.\n\n{interaction.user.name} now have {user_balances[user_id]} coins."
    else:
        result_message = f"The roulette landed on {result}.\nYOU LOSE... You lost {amount} coins.\n\n{interaction.user.name} now have {user_balances[user_id]} coins."

    # 通常のメッセージで結果を送信
    await interaction.followup.send(result_message)

# server_thread()
# bot.run(TOKEN)

bot.run(os.getenv('TOKEN'))