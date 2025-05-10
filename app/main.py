import discord
from discord import app_commands
from discord.ext import commands
import os
import random
import asyncio
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

user_balances = {}     # ユーザーの所持金を管理する辞書
last_daily_claim = {}  # ユーザーの日次報酬の最終受取日時を管理する辞書
daily_claim_count = {} # ユーザーの日次報酬の受け取り回数を管理する辞書
last_rob_attempt = {}  # ユーザーの最後の強奪実行日時を管理する辞書

blackjack_games = {}   # ブラックジャックのゲーム状態を管理する辞書

# ==============================================================================================

# ブラックジャック用のカードデッキを生成する関数
def create_deck():
    suits = ['♠', '♥', '♦', '♣']
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    return [f"{rank}{suit}" for suit in suits for rank in ranks]

# ----------------------------------------------------------------------------------------------

# カードの値を計算する関数
def calculate_hand_value(hand):
    value = 0
    aces = 0
    for card in hand:
        rank = card[:-1]  # カードのランク部分を取得
        if rank in ['J', 'Q', 'K']:
            value += 10
        elif rank == 'A':
            value += 11
            aces += 1
        else:
            value += int(rank)
    # Aを1として扱う場合の調整
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value

# ----------------------------------------------------------------------------------------------

# ターンを進める関数
def next_turn(game, channel):
    players = game["players"]
    current_index = players.index(next(player for player in players if player.id == game["current_turn"]))
    for i in range(1, len(players) + 1):
        next_index = (current_index + i) % len(players)
        next_player = players[next_index]
        if not game["game_state"][next_player.id]["stand"]:
            game["current_turn"] = next_player.id
            game["double_down_allowed"] = True
            # 手札がリセットされていないか確認
            if not game["game_state"][next_player.id]["hand"]:
                continue  # 手札が空の場合はスキップ
            return

    # 全員がスタンドした場合、ディーラーのターンを開始
    game["current_turn"] = "dealer"
    asyncio.create_task(start_dealer_turn(channel, game))  # ディーラーのターンを非同期で開始

# ----------------------------------------------------------------------------------------------

# ゲームの進行状況を更新する関数
async def update_game_state(channel, game):
    embed = discord.Embed(
        title="Blackjack Game State",
        color=discord.Color.blue()
    )

    # 各プレイヤーの手札を表示
    for player in game["players"]:
        player_state = game["game_state"][player.id]
        hand = player_state["hand"]
        hand_value = calculate_hand_value(hand)
        status = "Stand" if player_state["stand"] else "Playing"
        embed.add_field(
            name=f"{player.name}'s Hand",
            value=f"{', '.join(hand)} (Value: {hand_value}) - {status}",
            inline=False
        )

    # ディーラーの手札を表示
    dealer_hand = game["dealer_hand"]
    # ディーラーのターンでない場合は2枚目を隠す
    embed.add_field(
        name="Dealer's Hand",
        value=f"{dealer_hand[0]}, ❓",
        inline=False
    )

    # 現在のターンを表示
    if game["current_turn"] != "dealer":
        current_player = next(player for player in game["players"] if player.id == game["current_turn"])
        embed.add_field(name="Current Turn", value=f"It's {current_player.name}'s turn.", inline=False)

    await channel.send(embed=embed)

# ----------------------------------------------------------------------------------------------

async def start_dealer_turn(channel, game):
    dealer_hand = game["dealer_hand"]
    deck = game["deck"]
    dealer_value = calculate_hand_value(dealer_hand)

    # ディーラーがカードを引く
    while dealer_value < 17:
        card = deck.pop()
        dealer_hand.append(card)
        dealer_value = calculate_hand_value(dealer_hand)

    # 勝敗判定
    results = []
    for player in game["players"]:
        player_hand = game["game_state"][player.id]["hand"]
        player_value = calculate_hand_value(player_hand)

        if player_value > 21:
            result = f"{player.name}: Busted!"
            balance_change = f"-<:casino_tip2:1369628815709569044> {game['game_state'][player.id]['bet']}"
            user_balances[player.id] -= game["game_state"][player.id]["bet"]
        elif dealer_value > 21 or player_value > dealer_value:
            winnings = game["game_state"][player.id]["bet"] * 2
            user_balances[player.id] += winnings
            result = f"{player.name}: Won!"
            balance_change = f"+<:casino_tip2:1369628815709569044> {winnings}"
        elif player_value == dealer_value:
            result = f"{player.name}: Draw!"
            balance_change = "+<:casino_tip2:1369628815709569044> 0"
        else:
            loss = game["game_state"][player.id]["bet"]
            user_balances[player.id] -= loss
            result = f"{player.name}: Lost!"
            balance_change = f"-<:casino_tip2:1369628815709569044> {loss}"

        results.append(
            f"{result}\n**Balance Change**: {balance_change}\n**Current Balance**: <:casino_tip2:1369628815709569044> {user_balances[player.id]}"
        )

    # 結果を送信
    embed = discord.Embed(
        title="Blackjack Results",
        description="\n\n".join(results),
        color=discord.Color.green()
    )
    embed.add_field(
        name="Dealer's Hand",
        value=f"{', '.join(dealer_hand)} (Value: {dealer_value})",
        inline=False
    )
    await channel.send(embed=embed)

    # ゲームを終了
    try:
        del blackjack_games[channel.id]
    except KeyError:
        print(f"Debug: Attempted to delete non-existent game for channel ID {channel.id}")

# ----------------------------------------------------------------------------------------------

# プレイヤーごとの賭け金を設定
async def set_bets(interaction, game, players):
    channel = interaction.channel
    game_state = game["game_state"]

    for player in players:
        await channel.send(f"{player.mention}, please enter your bet amount (or type 'all' to bet all your coins).")

        def check(m):
            return m.author == player and m.channel == channel

        try:
            response = await bot.wait_for("message", timeout=60.0, check=check)
            bet_input = response.content.lower()

            # "all"が指定された場合、所持金全額を賭ける
            if bet_input == "all":
                bet = user_balances[player.id]
                if bet <= 0:
                    await channel.send(f"{player.mention}, you don't have any coins to bet.")
                    game_state[player.id]["bet"] = 0
                    continue
            else:
                try:
                    bet = int(bet_input)
                except ValueError:
                    await channel.send(f"{player.mention}, please enter a valid number.")
                    game_state[player.id]["bet"] = 0
                    continue

            # 賭け金の検証
            if bet <= 0:
                await channel.send(f"{player.mention}, please enter a valid bet amount.")
                game_state[player.id]["bet"] = 0
                continue

            if bet > user_balances[player.id]:
                await channel.send(f"{player.mention}, you don't have enough coins to bet that amount.")
                game_state[player.id]["bet"] = 0
                continue

            # 賭け金を保存
            game_state[player.id]["bet"] = bet
            await channel.send(f"{player.mention}, your bet of <:casino_tip2:1369628815709569044> {bet} coins has been placed.")

        except asyncio.TimeoutError:
            await channel.send(f"{player.mention}, you took too long to respond. Your bet has been set to 0.")
            game_state[player.id]["bet"] = 0
# ==============================================================================================

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
            user_balances[member.id] = 2000

# ==============================================================================================

# スラッシュコマンド: /help


# ==============================================================================================

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

    base_reward = 100  # 日次報酬の基本額
    bonus_reward = 100 # 7日毎のボーナス額

    if daily_claim_count.get(user_id, 0) % 7 == 6:
        base_reward += bonus_reward
        interaction.channel.send(
            f"{interaction.user.mention} has claimed their daily reward for the 7th time!\nThey received an extra {bonus_reward} coins!"
        )

    # 日次報酬を付与
    user_balances[user_id] = user_balances.get(user_id, 0) + base_reward
    last_daily_claim[user_id] = now  # 最終受取日時を更新

    # 日次報酬の受け取り回数を更新
    daily_claim_count[user_id] = daily_claim_count.get(user_id, 0) + 1

    embed = discord.Embed(
        title="Daily Reward",
        description=f"You have claimed your daily reward of <:casino_tip2:1369628815709569044> {base_reward} coins!\nYou now have <:casino_tip2:1369628815709569044> {user_balances[user_id]} coins.",
        color=discord.Color.green()
    )
    embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url)
    await interaction.response.send_message(embed=embed)

# ==============================================================================================

# スラッシュコマンド: /give
@bot.tree.command(name="give", description="Give coins to another user.")
@app_commands.describe(user="Select a user to give coins to", amount="Enter the amount of coins to give")
async def give(interaction: discord.Interaction, user: discord.Member, amount: int):
    giver_id = interaction.user.id
    receiver_id = user.id

    # 所持金の確認
    if giver_id not in user_balances or user_balances[giver_id] < amount:
        embed = discord.Embed(
            title="Error",
            description="You don't have enough coins to give.",
            color=discord.Color.red()
        )
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url)
        await interaction.response.send_message(embed=embed)
        return

    # 受取人の所持金を更新
    user_balances[giver_id] -= amount
    user_balances[receiver_id] = user_balances.get(receiver_id, 0) + amount

    embed = discord.Embed(
        title="Coins Given",
        description=f"You have given <:casino_tip2:1369628815709569044> {amount} coins to {user.name}.\nYou now have <:casino_tip2:1369628815709569044> {user_balances[giver_id]} coins.",
        color=discord.Color.green()
    )
    embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url)
    await interaction.response.send_message(embed=embed)

# ----------------------------------------------------------------------------------------------

# スラッシュコマンド: /rob
@bot.tree.command(name="rob", description="Rob coins from a random user.")
async def rob(interaction: discord.Interaction):
    robber_id = interaction.user.id
    now = datetime.now(JST)  # 現在の日本時間を取得

    # 最後の実行日時を確認
    if robber_id in last_rob_attempt:
        last_attempt_time = last_rob_attempt[robber_id]
        if last_attempt_time.date() == now.date():
            embed = discord.Embed(
                title="Robbery Limit Reached",
                description="You can only rob once per day. Please try again tomorrow!",
                color=discord.Color.red()
            )
            embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

    # 抽選対象のユーザーを取得（所持金が0より大きいユーザーのみ）
    eligible_users = [
        member for member in interaction.guild.members
        if not member.bot and user_balances.get(member.id, 0) > 0 and member.id != robber_id
    ]

    if not eligible_users:
        embed = discord.Embed(
            title="Error",
            description="No eligible users to rob. All users have 0 or negative balance.",
            color=discord.Color.red()
        )
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # 無作為に対象を選択
    victim = random.choice(eligible_users)
    victim_id = victim.id

    # 強奪額をランダムに設定（100～500の間）
    amount = random.randint(100, 500)

    # 50%の確率で強奪に失敗
    if random.random() < 0.5:
        # 強奪失敗: 実行者が被害者に所持金を奪われる
        if user_balances[robber_id] < amount:
            amount = user_balances[robber_id]  # 実行者の所持金が足りない場合、全額を奪われる

        user_balances[robber_id] -= amount
        user_balances[victim_id] += amount

        # 実行側に通知
        embed = discord.Embed(
            title="Robbery Failed!",
            description=f"You tried to rob {victim.name}, but failed!\n"
                        f"{victim.name} has robbed <:casino_tip2:1369628815709569044> {amount} coins from you instead.\n"
                        f"You now have <:casino_tip2:1369628815709569044> {user_balances[robber_id]} coins.",
            color=discord.Color.red()
        )
        embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url)
        await interaction.response.send_message(embed=embed)
        return

    # 強奪成功
    if user_balances[victim_id] < amount:
        amount = user_balances[victim_id]  # 被害者の所持金が足りない場合、全額を奪う

    user_balances[robber_id] += amount
    user_balances[victim_id] -= amount

    # 実行側に通知
    embed = discord.Embed(
        title="Robbery Successful!",
        description=f"You have successfully robbed <:casino_tip2:1369628815709569044> {amount} coins from {victim.name}.\n"
                    f"You now have <:casino_tip2:1369628815709569044> {user_balances[robber_id]} coins.",
        color=discord.Color.green()
    )
    embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url)
    await interaction.response.send_message(embed=embed)

    # 被害者側に通知
    embed_victim = discord.Embed(
        title="Robbery Alert!",
        description=f"You have been robbed by {interaction.user.name}!\n"
                    f"You lost <:casino_tip2:1369628815709569044> {amount} coins.\n"
                    f"You now have <:casino_tip2:1369628815709569044> {user_balances[victim_id]} coins.",
        color=discord.Color.red()
    )
    embed_victim.set_author(name=victim.name, icon_url=victim.display_avatar.url)
    await interaction.channel.send(embed=embed_victim)
    await interaction.channel.send(content=f"{victim.mention}")

    # 最後の実行日時を更新
    last_rob_attempt[robber_id] = now

# ==============================================================================================

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

# ----------------------------------------------------------------------------------------------

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

# ==============================================================================================

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

# ----------------------------------------------------------------------------------------------

# スラッシュコマンド: /blackjack
@bot.tree.command(name="blackjack", description="Play blackjack. Usage: /blackjack <amount>")
@app_commands.describe(amount="The amount to bet (or type 'all' to bet all your coins)")
async def blackjack(interaction: discord.Interaction, amount: str):
    channel_id = interaction.channel.id
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

    # デッキを作成してシャッフル
    deck = create_deck()
    random.shuffle(deck)

    # プレイヤーとディーラーの手札を配る
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]

    # ゲーム状態を保存
    blackjack_games[channel_id] = {
        "mode": "single",
        "deck": deck,
        "player_hand": player_hand,
        "dealer_hand": dealer_hand,
        "bet": amount,
        "current_turn": user_id,
        "double_down_allowed": True
    }

    # ナチュラル21の判定
    player_value = calculate_hand_value(player_hand)
    dealer_value = calculate_hand_value(dealer_hand)

    if player_value == 21:
        if dealer_value == 21:
            # 引き分け
            embed = discord.Embed(
                title="Blackjack - It's a Draw!",
                description=(
                    f"**Your Hand**: {', '.join(player_hand)} (Value: 21)\n"
                    f"**Dealer's Hand**: {', '.join(dealer_hand)} (Value: 21)\n\n"
                    "It's a draw! Your balance remains the same.\n"
                    f"Your new balance is <:casino_tip2:1369628815709569044> {user_balances[user_id]} coins."
                ),
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed)
            del blackjack_games[channel_id]  # ゲームを終了
            return
        else:
            # プレイヤーの勝利（ナチュラル21）
            winnings = int(amount * 2.5)
            user_balances[user_id] += winnings
            embed = discord.Embed(
                title="Blackjack - Natural 21!",
                description=(
                    f"**Your Hand**: {', '.join(player_hand)} (Value: 21)\n"
                    f"**Dealer's Hand**: {', '.join(dealer_hand)} (Value: {dealer_value})\n\n"
                    f"You got a Natural 21! You win <:casino_tip2:1369628815709569044> {winnings} coins.\n"
                    f"Your new balance is <:casino_tip2:1369628815709569044> {user_balances[user_id]} coins."
                ),
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
            del blackjack_games[channel_id]  # ゲームを終了
            return

    # プレイヤーとディーラーの手札を表示（ディーラーの2枚目は裏向き）
    embed = discord.Embed(
        title="Blackjack",
        description=(
            f"**Your Hand**: {', '.join(player_hand)} (Value: {calculate_hand_value(player_hand)})\n"
            f"**Dealer's Hand**: {dealer_hand[0]}, ❓"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="Type '/hit' to draw another card or '/stand' to end your turn.")
    await interaction.response.send_message(embed=embed)

# ----------------------------------------------------------------------------------------------

# スラッシュコマンド: /multi_bj
@bot.tree.command(name="multi_bj", description="Start a multiplayer blackjack game. Up to 4 players can join.")
async def multi_bj(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    user_id = interaction.user.id

    if user_id not in user_balances:
        user_balances[user_id] = 0  # 所持金が未設定の場合は0に初期化

    # 賭け金の検証
    max_bet = 5000 if user_balances[user_id] >= 0 else 500

    # 募集メッセージを送信
    embed = discord.Embed(
        title="Multiplayer Blackjack",
        description=(
            "React with 🎮 to join the game!\n"
            "React with ✅ to start the game immediately (at least 2 players required).\n"
            "Up to 4 players can join.\n"
            "The game will start in 60 seconds or when 4 players join."
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Hosted by {interaction.user.name}", icon_url=interaction.user.avatar.url)
    await interaction.response.send_message(embed=embed)

    message = await interaction.original_response()

    # 募集用のリアクションを追加
    await message.add_reaction("🎮")
    await message.add_reaction("✅")  # Botがチェックマークを送信

    # プレイヤーリストを管理
    players = [interaction.user]  # コマンド実行者は自動的に参加
    max_players = 4

    def check_reaction(reaction, user):
        return (
            reaction.message.id == message.id
            and str(reaction.emoji) in ["🎮", "✅"]
            and not user.bot
        )

    # 60秒間リアクションを待機
    try:
        while len(players) < max_players:
            reaction, user = await bot.wait_for("reaction_add", timeout=60.0, check=check_reaction)

            if str(reaction.emoji) == "🎮" and user not in players:
                players.append(user)
                await message.channel.send(f"{user.name} has joined the game! ({len(players)}/{max_players})")

            # チェックマークが押された場合、2人以上で強制開始
            if str(reaction.emoji) == "✅" and len(players) >= 2:
                await message.channel.send("✅ reaction received! Starting the game immediately.")
                break
    except TimeoutError:
        pass

    # ゲーム状態を初期化
    blackjack_games[channel_id] = {
        "mode": "multi",
        "deck": create_deck(),
        "players": players,
        "game_state": {player.id: {"hand": [], "stand": False, "bet": 0} for player in players},
        "dealer_hand": [],
        "current_turn": players[0].id,
        "double_down_allowed": True
    }

    game = blackjack_games[channel_id]

    # プレイヤーが1人以下の場合、ゲームをキャンセル
    if len(players) < 2:
        await message.channel.send("Not enough players to start the game. The game has been canceled.")
        return

    # 賭け金を設定
    await set_bets(interaction, blackjack_games[channel_id], players)

    # 賭け金が1人でも0の場合、ゲームをキャンセル
    if any(game["game_state"][player.id]["bet"] == 0 for player in players):
        await message.channel.send("At least one player did not place a valid bet. The game has been canceled.")
        del blackjack_games[channel_id]
        return

    # ゲーム開始
    await message.channel.send(f"The game is starting with {len(players)} players: {', '.join([player.name for player in players])}!")

    # デッキを作成してシャッフル
    deck = create_deck()
    random.shuffle(deck)

    # 各プレイヤーに手札を配る
    game_state = {player.id: {"hand": [deck.pop(), deck.pop()], "stand": False, "bet": game["game_state"][player.id]["bet"]} for player in players}
    dealer_hand = [deck.pop(), deck.pop()]
    blackjack_games[channel_id]["game_state"] = game_state
    blackjack_games[channel_id]["dealer_hand"] = dealer_hand

    game = blackjack_games[channel_id]  # gameオブジェクトを取得

    # プレイヤーに手札を送信
    embed = discord.Embed(
        title="Blackjack Hands",
        color=discord.Color.blue()
    )

    for player in players:
        if player.id in game_state:
            player_hand = game_state[player.id]["hand"]
            embed.add_field(
                name=f"{player.name}'s Hand",
                value=f"{', '.join(player_hand)} (Value: {calculate_hand_value(player_hand)})",
                inline=False
            )

    # ディーラーの手持ちを表示（2枚目は裏向き）
    embed.add_field(
        name="Dealer's Hand",
        value=f"{dealer_hand[0]}, ❓",
        inline=False
    )

    embed.set_footer(text="Type '/hit' to draw another card or '/stand' to end your turn.")
    await interaction.channel.send(embed=embed)

    # ディーラーの手札を作成
    dealer_hand = [deck.pop(), deck.pop()]
    dealer_value = calculate_hand_value(dealer_hand)

    # ゲーム進行
    while any(not state["stand"] for state in game_state.values()):
        for player in players:
            if game_state[player.id]["stand"]:
                continue

            # プレイヤーのターンを進行
            await message.channel.send(f"{player.name}'s turn! Type '/hit' to draw a card or '/stand' to end your turn.")
            try:
                response = await bot.wait_for(
                    "message",
                    check=lambda m: m.author == player and m.content.lower() in ["/hit", "/stand"]
                )
            except TimeoutError:
                await message.channel.send(f"{player.mention} You took too long to respond. Your turn has been skipped.")
                game_state[player.id]["stand"] = True
                continue

            if response.content.lower() == "/hit":
                # カードを引く
                card = deck.pop()
                game_state[player.id]["hand"].append(card)
                hand_value = calculate_hand_value(game_state[player.id]["hand"])

                # 手札を送信
                embed = discord.Embed(
                    title="Your Blackjack Hand",
                    description=f"Your hand: {', '.join(game_state[player.id]['hand'])} (Value: {hand_value})",
                    color=discord.Color.blue()
                )
                await player.send(embed=embed)

                # バースト判定
                if hand_value > 21:
                    await player.send("You went over 21! You have been eliminated from the game.")
                    game_state[player.id]["stand"] = True
            elif response.content.lower() == "/stand":
                # スタンド
                game_state[player.id]["stand"] = True
                await player.send("You have chosen to stand.")

    # ディーラーのターン
    dealer_hand = game["dealer_hand"]  # game["dealer_hand"]を参照
    dealer_value = calculate_hand_value(dealer_hand)
    while dealer_value < 17:
        card = game["deck"].pop()  # デッキからカードを引く
        dealer_hand.append(card)  # game["dealer_hand"]を直接更新
        dealer_value = calculate_hand_value(dealer_hand)  # 更新後の値を再計算

    # 勝敗判定
    results = []
    for player in game["players"]:
        player_hand = game["game_state"][player.id]["hand"]
        player_value = calculate_hand_value(player_hand)

        if player_value > 21:
            result = f"{player.name}: Busted!"
        elif dealer_value > 21 or player_value > dealer_value:
            result = f"{player.name}: Won!"
        elif player_value == dealer_value:
            result = f"{player.name}: Draw!"
        else:
            result = f"{player.name}: Lost!"
        results.append(result)

    # 結果を送信
    embed = discord.Embed(
        title="Blackjack Results",
        description="\n".join(results),
        color=discord.Color.green()
    )
    embed.add_field(
        name="Dealer's Hand",
        value=f"{', '.join(dealer_hand)} (Value: {dealer_value})",
        inline=False
    )
    await message.channel.send(embed=embed)

# ----------------------------------------------------------------------------------------------

# ブラックジャックの "hit" コマンド
@bot.tree.command(name="hit", description="Draw another card in blackjack.")
async def hit(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    user_id = interaction.user.id

    # ゲームが存在するか確認
    if channel_id not in blackjack_games:
        await interaction.response.send_message("You are not currently in a blackjack game.", ephemeral=True)
        return

    game = blackjack_games[channel_id]

    # シングルプレイヤーモードの場合
    if game["mode"] == "single":
        if user_id != game["current_turn"]:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        deck = game["deck"]
        player_hand = game["player_hand"]

        # カードを引く
        card = deck.pop()
        player_hand.append(card)
        hand_value = calculate_hand_value(player_hand)

        # バースト判定
        if hand_value > 21:
            bet = game["bet"]
            user_balances[user_id] -= bet
            del blackjack_games[channel_id]  # ゲームを終了
            embed = discord.Embed(
                title="Blackjack - You Lose!",
                description=(
                    f"**Your Hand**: {', '.join(player_hand)} (Value: {hand_value})\n"
                    f"**Dealer's Hand**: {', '.join(game['dealer_hand'])} (Value: {calculate_hand_value(game['dealer_hand'])})\n\n"
                    f"You went over 21 and lost <:casino_tip2:1369628815709569044> {bet} coins.\n"
                    f"Your new balance is <:casino_tip2:1369628815709569044> {user_balances[user_id]} coins."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return

        # 手札を表示
        embed = discord.Embed(
            title="Blackjack",
            description=f"**Your Hand**: {', '.join(player_hand)} (Value: {hand_value})\n**Dealer's Hand**: {game['dealer_hand'][0]}, ❓",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Type '/hit' to draw another card or '/stand' to end your turn.")
        await interaction.response.send_message(embed=embed)

    # マルチプレイヤーモードの場合
    elif game["mode"] == "multi":
        if game["current_turn"] != user_id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        player_state = game["game_state"][user_id]
        deck = game["deck"]

        # カードを引く
        card = deck.pop()
        player_state["hand"].append(card)
        hand_value = calculate_hand_value(player_state["hand"])

        # バースト判定
        if hand_value > 21:
            player_state["stand"] = True
            embed = discord.Embed(
                title="Blackjack - You Busted!",
                description=f"**Your hand**: {', '.join(player_state['hand'])} (Value: {hand_value})\nYou went over 21!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(
                title="Your Blackjack Hand",
                description=f"**Your hand**: {', '.join(player_state['hand'])} (Value: {hand_value})\n**Dealer's Hand**: {game['dealer_hand'][0]}, ❓",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)

        # 次のターンに進む
        next_turn(game, interaction.channel)

        # 全員がスタンドした場合、ゲームを終了
        if all(player_state["stand"] for player_state in game["game_state"].values()):
            del blackjack_games[channel_id]
            return

        # ゲームの進行状況を更新
        await update_game_state(interaction.channel, game)

# ----------------------------------------------------------------------------------------------

# ブラックジャックの "stand" コマンド
@bot.tree.command(name="stand", description="End your turn in blackjack.")
async def stand(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    user_id = interaction.user.id

    # ゲームが存在するか確認
    if channel_id not in blackjack_games:
        await interaction.response.send_message("You are not currently in a blackjack game.", ephemeral=True)
        return

    game = blackjack_games[channel_id]

    # シングルプレイヤーモードの場合
    if game["mode"] == "single":
        if user_id != game["current_turn"]:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        # ディーラーのターン
        dealer_hand = game["dealer_hand"]
        deck = game["deck"]
        dealer_value = calculate_hand_value(dealer_hand)
        while dealer_value < 17:
            dealer_hand.append(deck.pop())
            dealer_value = calculate_hand_value(dealer_hand)

        player_hand = game["player_hand"]
        player_value = calculate_hand_value(player_hand)

        # 勝敗判定
        if dealer_value > 21 or player_value > dealer_value:
            winnings = game["bet"] * 2
            user_balances[user_id] += winnings
            result = "You Win!"
            color = discord.Color.green()
            balance_change = f"+<:casino_tip2:1369628815709569044> {winnings}"
        elif player_value == dealer_value:
            result = "It's a Draw!"
            color = discord.Color.orange()
            balance_change = "+<:casino_tip2:1369628815709569044> 0"
        else:
            loss = game["bet"]
            user_balances[user_id] -= loss
            result = "You Lose!"
            color = discord.Color.red()
            balance_change = f"-<:casino_tip2:1369628815709569044> {loss}"

        # ゲームを終了
        del blackjack_games[channel_id]

        # 結果を表示
        embed = discord.Embed(
            title=f"Blackjack - {result}",
            description=(
                f"**Your Hand**: {', '.join(player_hand)} (Value: {player_value})\n"
                f"**Dealer's Hand**: {', '.join(dealer_hand)} (Value: {dealer_value})\n\n"
                f"**Balance Change**: {balance_change}\n"
                f"**Current Balance**: <:casino_tip2:1369628815709569044> {user_balances[user_id]}"
            ),
            color=color
        )
        await interaction.response.send_message(embed=embed)

    # マルチプレイヤーモードの場合
    elif game["mode"] == "multi":
        if game["current_turn"] != user_id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        # プレイヤーの状態を更新
        game["game_state"][user_id]["stand"] = True

        embed = discord.Embed(
            title="You Chose to Stand",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

        # 次のターンに進む
        next_turn(game, interaction.channel)

        # ゲームの進行状況を更新
        await update_game_state(interaction.channel, game)

# ----------------------------------------------------------------------------------------------

# ブラックジャックの "double_down" コマンド
@bot.tree.command(name="double_down", description="Double your bet and draw one card in blackjack.")
async def double_down(interaction: discord.Interaction):
    channel_id = interaction.channel.id
    user_id = interaction.user.id

    # ゲームが存在するか確認
    if channel_id not in blackjack_games:
        await interaction.response.send_message("You are not currently in a blackjack game.", ephemeral=True)
        return

    game = blackjack_games[channel_id]

    # ダブルダウンが許可されているか確認
    if not game.get("double_down_allowed", False):
        await interaction.response.send_message("You can only double down immediately after the first two cards are dealt.", ephemeral=True)
        return

    # シングルプレイヤーモードの場合
    if game["mode"] == "single":
        player_hand = game["player_hand"]
        bet = game["bet"]

        # 賭け金を倍にする
        bet *= 2

        # プレイヤーにカードを1枚配る
        card = game["deck"].pop()
        player_hand.append(card)
        player_value = calculate_hand_value(player_hand)

        # ダブルダウン後はフラグを無効化
        game["double_down_allowed"] = False

        # ディーラーのターン
        dealer_hand = game["dealer_hand"]
        deck = game["deck"]
        dealer_value = calculate_hand_value(dealer_hand)
        while dealer_value < 17:
            dealer_hand.append(deck.pop())
            dealer_value = calculate_hand_value(dealer_hand)

        player_hand = game["player_hand"]
        player_value = calculate_hand_value(player_hand)

        # バースト判定
        if player_value > 21:
            user_balances[user_id] -= bet
            del blackjack_games[channel_id]  # ゲームを終了
            embed = discord.Embed(
                title="Blackjack - You Lose!",
                description=(
                    f"**Your Hand**: {', '.join(player_hand)} (Value: {player_value})\n"
                    f"**Dealer's Hand**: {', '.join(game['dealer_hand'])} (Value: {calculate_hand_value(game['dealer_hand'])})\n\n"
                    f"You went over 21 and lost <:casino_tip2:1369628815709569044> {bet} coins.\n"
                    f"Your new balance is <:casino_tip2:1369628815709569044> {user_balances[user_id]} coins."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return

        # 勝敗判定
        if dealer_value > 21 or player_value > dealer_value:
            winnings = bet * 2
            user_balances[user_id] += winnings
            result = "You Win!"
            color = discord.Color.green()
            balance_change = f"+<:casino_tip2:1369628815709569044> {winnings}"
        elif player_value == dealer_value:
            result = "It's a Draw!"
            color = discord.Color.orange()
            balance_change = "+<:casino_tip2:1369628815709569044> 0"
        else:
            loss = bet
            user_balances[user_id] -= loss
            result = "You Lose!"
            color = discord.Color.red()
            balance_change = f"-<:casino_tip2:1369628815709569044> {loss}"

        # ゲームを終了
        del blackjack_games[channel_id]

        # 結果を表示
        embed = discord.Embed(
            title=f"Blackjack - {result}",
            description=(
                f"**Your Hand**: {', '.join(player_hand)} (Value: {player_value})\n"
                f"**Dealer's Hand**: {', '.join(dealer_hand)} (Value: {dealer_value})\n\n"
                f"**Balance Change**: {balance_change}\n"
                f"**Current Balance**: <:casino_tip2:1369628815709569044> {user_balances[user_id]}"
            ),
            color=color
        )
        await interaction.response.send_message(embed=embed)

    # マルチプレイヤーモードの場合
    elif game["mode"] == "multi":
        if game["current_turn"] != user_id:
            await interaction.response.send_message("It's not your turn!", ephemeral=True)
            return

        # プレイヤーの状態を更新
        game["game_state"][user_id]["stand"] = True

        player_state = game["game_state"][user_id]

        player_hand = player_state["hand"]
        bet = player_state["bet"]

        # 賭け金を倍にする
        player_state["bet"] *= 2
        if user_balances[user_id] < player_state["bet"]:
            await interaction.response.send_message("You don't have enough coins to double your bet.", ephemeral=True)
            return

        # プレイヤーにカードを1枚配る
        card = game["deck"].pop()
        player_hand.append(card)
        player_value = calculate_hand_value(player_hand)

        # ダブルダウン後はフラグを無効化
        game["double_down_allowed"] = False

        # バースト判定
        if player_value > 21:
            player_state["stand"] = True
            embed = discord.Embed(
                title="Blackjack - You Busted!",
                description=f"**Your hand**: {', '.join(player_hand)} (Value: {player_value})\nYou went over 21!",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
        else:
            embed = discord.Embed(
                title="Your Blackjack Hand",
                description=f"**Your hand**: {', '.join(player_hand)} (Value: {player_value})\n**Dealer's Hand**: {game['dealer_hand'][0]}, ❓",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)

        # 次のターンに進む
        next_turn(game, interaction.channel)

        # 全員がスタンドした場合、ゲームを終了
        if all(player_state["stand"] for player_state in game["game_state"].values()):
            del blackjack_games[channel_id]
            return

        # ゲームの進行状況を更新
        await update_game_state(interaction.channel, game)

# server_thread()
# bot.run(TOKEN)
bot.run(os.getenv('TOKEN'))