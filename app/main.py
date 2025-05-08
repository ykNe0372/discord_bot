import discord
from discord import app_commands
from discord.ext import commands
import os
import random
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from server import server_thread

load_dotenv()

# TOKEN = os.environ.get('TOKEN')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

JST = timezone(timedelta(hours=+9))

bot = commands.Bot(command_prefix="/", intents=intents)

# ユーザーの所持金を管理する辞書
user_balances = {}

# ユーザーの日次報酬の最終受取日時を管理する辞書
last_daily_claim = {}

# ユーザーの日次報酬の受け取り回数を管理する辞書
daily_claim_count = {}

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

# スラッシュコマンド: /help


# スラッシュコマンド: /daily
@bot.tree.command(name="daily", description="Claim your daily reward.")
async def daily(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = datetime.now(JST)

    # 最後の受取日時を取得
    if user_id in last_daily_claim:
        last_claim_time = last_daily_claim[user_id]
        if last_claim_time.date() == now.date():
            embed = discord.Embed(
                title="Daily Reward",
                description="You have already claimed your daily reward today.",
                color=discord.Color.red()
            )
            embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url)
            await interaction.response.send_message(embed=embed)
            return

    # 日次報酬の基本額
    base_reward = 100

    if daily_claim_count.get(user_id, 0) % 7 == 6:
        base_reward += 100
        interaction.channel.send(
            f"{interaction.user.mention} has claimed their daily reward for the 7th time!\nThey received an extra {base_reward} coins!"
        )

    # 日次報酬を付与
    user_balances[user_id] = user_balances.get(user_id, 0) + base_reward
    last_daily_claim[user_id] = now  # 最終受取日時を更新

    # 日次報酬の受け取り回数を更新
    daily_claim_count[user_id] = daily_claim_count.get(user_id, 0) + 1

    embed = discord.Embed(
        title="Daily Reward",
        description=f"You have claimed your daily reward of 100 coins!\nYou now have {user_balances[user_id]} coins.",
        color=discord.Color.green()
    )
    embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url)
    await interaction.response.send_message(embed=embed)

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
            description=f"{target_user.name} has {"<:casino_tip2:1369628815709569044>"} {balance}.",
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

    balances = sorted(balances, key=lambda x: x[1], reverse=True)  # 所持金でソート

    # Embedメッセージで出力
    embed = discord.Embed(
        title="All Members' Balances",
        color=discord.Color.blue()
    )

    for name, balance in balances:
        embed.add_field(
            name=name,
            value=f"<:casino_tip2:1369628815709569044> {balance} coins",
            inline=False
        )

    embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=interaction.user.avatar.url)
    await interaction.response.send_message(embed=embed)

# スラッシュコマンド: /roulette
@bot.tree.command(name="roulette", description="Play roulette. Usage: /roulette <amount> <option> <number>")
@app_commands.describe(amount="The amount to bet (or type 'all' to bet all your coins)", option="Choose your bet option", number="Choose a number between 0 and 36 (only for 'Number')")
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
async def roulette(interaction: discord.Interaction, amount: str, option: app_commands.Choice[str], number: int = None):
    # 入力の検証
    if option.value == "number" and (number is None or number < 0 or number > 36):
        await interaction.response.send_message("Please specify a valid number between 0 and 36 after selecting 'Number'.", ephemeral=True)
        return

    user_id = interaction.user.id
    if user_id not in user_balances:
        user_balances[user_id] = 0  # 所持金が未設定の場合は0に初期化

    # 賭け金の検証
    max_bet = 5000 if user_balances[user_id] >= 0 else 500

    # "all"が指定された場合、所持金全額を賭ける
    if amount.lower() == "all":
        amount = user_balances[user_id]
        if amount <= 0:
            await interaction.response.send_message("You don't have any coins to bet.", ephemeral=True)
            return
    else:
        try:
            amount = int(amount)
        except ValueError:
            await interaction.response.send_message("Please enter a valid number for the bet amount.", ephemeral=True)
            return

    if amount <= 0:
        await interaction.response.send_message("Please enter a valid bet amount.", ephemeral=True)
        return

    # all以外の時に、賭け金が最大賭け金を超えている場合
    if amount != user_balances[user_id] and amount > max_bet:
        await interaction.response.send_message(f"Your bet amount exceeds the maximum limit of <:casino_tip2:1369628815709569044> {max_bet}.", ephemeral=True)
        return

    # 賭け金が所持金を超えている場合の警告を追加
    if user_balances[user_id] >= 0 and user_balances[user_id] < amount:
        channel = interaction.channel
        await channel.send(
            f"{interaction.user.mention}\nWarning: You are betting more than your current balance <:casino_tip2:1369628815709569044> {user_balances[user_id]}.\nYour balance will go negative if you lose."
        )

    # Embedメッセージで賭け情報を送信
    embed_description = (
        f"**Bet Amount**\n<:casino_tip2:1369628815709569044> {amount} coins\n\n"
        f"**Bet Option**\n{option.name}\n"
    )
    if option.value == "number":
        embed_description += f"\n**Chosen Number**\n{number}"

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
            result_message = f"The roulette landed on {result}.\nYOU WIN! The number matched! You gained <:casino_tip2:1369628815709569044> {amount * 36}.\n\n{interaction.user.name} now have <:casino_tip2:1369628815709569044> {user_balances[user_id]}."
        else:
            result_message = f"The roulette landed on {result}.\nYOU LOSE... The number didn't match. You lost <:casino_tip2:1369628815709569044> {amount}.\n\n{interaction.user.name} now have <:casino_tip2:1369628815709569044> {user_balances[user_id]}."
    elif option.value == "small" and 1 <= result <= 12:
        user_balances[user_id] += amount * 3
        result_message = f"The roulette landed on {result}.\nYOU WIN! The range matched! You gained <:casino_tip2:1369628815709569044> {amount * 3}.\n\n{interaction.user.name} now have <:casino_tip2:1369628815709569044> {user_balances[user_id]}."
    elif option.value == "medium" and 13 <= result <= 24:
        user_balances[user_id] += amount * 3
        result_message = f"The roulette landed on {result}.\nYOU WIN! The range matched! You gained <:casino_tip2:1369628815709569044> {amount * 3}.\n\n{interaction.user.name} now have <:casino_tip2:1369628815709569044> {user_balances[user_id]}."
    elif option.value == "large" and 25 <= result <= 36:
        user_balances[user_id] += amount * 3
        result_message = f"The roulette landed on {result}.\nYOU WIN! The range matched! You gained <:casino_tip2:1369628815709569044> {amount * 3}.\n\n{interaction.user.name} now have <:casino_tip2:1369628815709569044> {user_balances[user_id]}."
    elif option.value == "first" and 1 <= result <= 18:
        user_balances[user_id] += amount * 2
        result_message = f"The roulette landed on {result}.\nYOU WIN! The range matched! You gained <:casino_tip2:1369628815709569044> {amount * 2}.\n\n{interaction.user.name} now have <:casino_tip2:1369628815709569044> {user_balances[user_id]}."
    elif option.value == "second" and 19 <= result <= 36:
        user_balances[user_id] += amount * 2
        result_message = f"The roulette landed on {result}.\nYOU WIN! The range matched! You gained <:casino_tip2:1369628815709569044> {amount * 2}.\n\n{interaction.user.name} now have <:casino_tip2:1369628815709569044> {user_balances[user_id]}."
    elif option.value == "even" and result_type == "even":
        user_balances[user_id] += amount * 2
        result_message = f"The roulette landed on {result} ({result_type}).\nYOU WIN! You gained <:casino_tip2:1369628815709569044> {amount * 2}.\n\n{interaction.user.name} now have <:casino_tip2:1369628815709569044> {user_balances[user_id]}."
    elif option.value == "odd" and result_type == "odd":
        user_balances[user_id] += amount * 2
        result_message = f"The roulette landed on {result} ({result_type}).\nYOU WIN! You gained <:casino_tip2:1369628815709569044> {amount * 2}.\n\n{interaction.user.name} now have <:casino_tip2:1369628815709569044> {user_balances[user_id]}."
    else:
        result_message = f"The roulette landed on {result}.\nYOU LOSE... You lost <:casino_tip2:1369628815709569044> {amount}.\n\n{interaction.user.name} now have <:casino_tip2:1369628815709569044> {user_balances[user_id]}."

    # 通常のメッセージで結果を送信
    await interaction.followup.send(result_message)

# server_thread()
# bot.run(TOKEN)

bot.run(os.getenv('TOKEN'))