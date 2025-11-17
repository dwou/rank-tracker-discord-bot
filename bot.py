""" Module providing primary interface for the bot. """

# Not (yet) implemented:
#   A customized ping system based on region/platform/Elo (not useful for now)
#   API rate limiter (but shouldn't be a problem)

# TODO: add punctiation to comments
# TODO: fix issue of pinging roles not pinging
# TODO: process match log to re-compute Elo upon startup (including using "undo")
# TODO: figure out how to update
# TODO: idenfity bug that sometimes breaks `playerdata`

# Note: "admin" here means that people have the "ban_members" permission

from os import getenv
import re
from typing import Literal
import asyncio

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

from _players import PlayerManager, Player
from lobby_manager import LobbyManager
from basic_functions import debug_print, async_cache

AUTOSAVE = True
AUTOSAVE_BACKUPS = True # whether to back up previous data while autosaving
AUTOSAVE_PERIOD = 10*60 # seconds between each autosave
REPORT_STR = "Report bugs to DWouu." # string to append to certain messages
# Note: HELP_STRING does not include admin-only commands
HELP_STRING = """-# Note: "lobby" here refers to the object which this Discord bot keeps track of internally.
```
/ranked <region> <platform> <ping_users={True|False}>
        Open a ranked lobby and optionally ping users in the region/platform.
        The lobby must be periodically updated using /result.

/invite <user>
        Allow a player to join your lobby.

/join <user>
        Join a lobby (you need to be invited first).

/leave
        Leave a lobby.

/result {I won|I lost|Draw|Undo}
        Report the result of a match (must be in a lobby with the other player).
        Note: "Undo" has not been implemented yet but will be logged for later.

--------------------------------------------------------------------------------

/list_lobbies
        List the open lobbies.

/playerdata <user>
        Display the ranked data of a user.

/leaderboard <region> <platform>
        Display the ranked leaderboard for a region/platform.

!ping
        A simple ping-ping test to check if the bot is online.```"""\
    + f"**{REPORT_STR}**"


# NOTES: Types & naming conventions, Functions, Data
'''
"msg": discord.message.Message  # a Discord message
  .channel
    .send()                # send a message in the message's channel
  .content: str            # the message's content
  .author                  # the author, a Member
"user" discord.member.Member
  .guild_permissions
    .administrator: bool   # is an admin
  .mention: str?           # the username
  .bot: bool               # is a bot
  .display_name            # the display name of the user
  .global_name             # like `display_name` but sometimes returns None (?)
"itx" discord.Interaction  # for slash commands (among other things?)
  .response
    .send_message()        # Send a message in response to the itx
  .user: Member            # the message sender
  .channel
"ctx" discord.ext.commands.context.Context  # it's like a Member
  .send                    # send a message; different from channel.send()?
'''
# Note: you have to explicitly enable pinging in messages with `allowed_mentions`


###############
# Main/global #
###############


# get "intents" (incoming messages, reactions etc) and create the bot
intents = discord.Intents.default()
intents.message_content = True  # see (incoming messages'?) content
bot = commands.Bot(command_prefix="!", intents=intents)


async def main():
  """ Initialize PlayerManager, start autosave, and start the bot. """
  PlayerManager.initialize()
  if AUTOSAVE:
    asyncio.create_task(
      PlayerManager.autosave(period=AUTOSAVE_PERIOD, backup=AUTOSAVE_BACKUPS)
    )
  load_dotenv()
  await bot.start(getenv("DISCORD_TOKEN"))


##################
# Events/intents #
##################


@bot.event
async def on_ready() -> None:
  """ When the bot starts up, sync the bot's commands. """
  await bot.tree.sync()
  debug_print(f"{bot.user} is online!")


@bot.event
async def on_message(msg: discord.message.Message) -> None:
  """ Handle new messages. """
  # Drop DMs
  if not msg.guild:
    return

  # Print message
  debug_print(msg.clean_content)

  # Ignore bots' messages
  is_bot: bool = msg.author.bot
  if is_bot:
    return

  # Handle automatic replies
  await handle_autoreply(msg)

  # Execute ! commands
  await bot.process_commands(msg)


@bot.event
async def on_interaction(itx: discord.Interaction):
  """ Log incoming slash commands. """
  if itx.type == discord.InteractionType.application_command:
    command = itx.data['name']
    # check if there are arguments passed
    if 'options' in itx.data:
      options_text = ' '.join([
        f"{option['name']}:{option['value']}"
        for option in itx.data['options']
      ])
    else:
      options_text = ''

    debug_print(f"[{itx.user.display_name}] /{command} {options_text}")


##################
# Slash commands #
##################


@app_commands.default_permissions(ban_members=True)
@bot.tree.command(name='save', description='Saves player data')
async def save(
    itx: discord.Interaction,
    backup: bool,
  ) -> None:
  """ Manually save player data. """
  debug_print('Manually saving PlayerManager...')
  PlayerManager.save_to_file(backup=backup)
  await itx.response.send_message('Saved.', ephemeral=True)


@bot.tree.command(name='playerdata', description='Print player data')
async def playerdata(
    itx: discord.Interaction,
    user: discord.User,
  ) -> None:
  """ Display data about a player. """
  try:
    player = get_player(user)
    response = player.get_summary()
    await itx.response.send_message(response, ephemeral=True)
  except Exception as e:
    debug_print(e.args)


@bot.tree.command(name='help', description="Show a description of each command")
async def help(itx: discord.Interaction) -> None:
  """ Print the `help` text; same as /bot_commands. """
  await itx.response.send_message(HELP_STRING, ephemeral=True)


@bot.tree.command(name='bot_commands', description="Show a description of each command")
async def bot_commands(itx: discord.Interaction) -> None:
  """ Print a description of each command; same as /help. """
  await itx.response.send_message(HELP_STRING, ephemeral=True)


@bot.tree.command(name='ranked', description='Open a ranked session')
async def ranked(
    itx: discord.Interaction,
    region: Literal['NA', 'EU', 'ASIA', 'SA', 'MEA'],
    platform: Literal['Steam', 'PS'], # use "Steam", as "PS" ~= "PC" visually
    ping_users: Literal['Ping users', "Don't ping users"],
  ) -> None:
  """ Open a ranked lobby given region and platform,
      and optionally ping users that use the role. """
  if platform == 'Steam':
    platform = 'PC'
  user = itx.user
  this_player = get_player(user)

  # Try making a new lobby for this player and proceed if a new lobby is made.
  try:
    _ = await LobbyManager.new_lobby(this_player, region, platform)
  except ValueError as e:
    debug_print(e.args)
    await itx.response.send_message(
      f"ERROR: {e.args}",
      ephemeral=True
    )
    return

  # Format and send the "created a lobby" message.
  footer = f"_-# **{REPORT_STR}**_"
  if ping_users == "Ping users":
    role_name = f"{region}-T7-{platform}"
    role = discord.utils.get(itx.guild.roles, name=role_name)
    header = f"{role.mention} :speaking_head::mega: {user.mention}"\
      " just opened a ranked lobby!\n"
    body = this_player.get_summary()
    text = header + '\n' + body + footer
  else:
    header = f"{user.mention} opened a ranked lobby.\n"
    text = header + footer

  await itx.response.send_message(
    text,
    allowed_mentions=discord.AllowedMentions(roles=True),
    ephemeral=False
  )

  # Add a reminder to the sender to invite people.
  note = "Don't forget to `/invite` people."
  if ping_users == "Don't ping users":
    note += " Note that users were not \"pinged\" (notified)."
  await itx.followup.send(note, ephemeral=True)


@bot.tree.command(name='invite', description='Invite another user to a ranked session')
async def invite(
    itx: discord.Interaction,
    invited_user: discord.User,
  ) -> None:
  """ The caller invites another user to their lobby. """
  try:
    host = itx.user
    host_player = get_player(host)
    invited_player = get_player(invited_user)
    LobbyManager.invite_to_lobby(host_player, invited_player)
    text = f"{host.mention} invited {invited_user.mention}"\
      "\n-# use `/join` to join their lobby"
    await itx.response.send_message(text)
  except Exception as e:
    await itx.response.send_message(f"ERROR: {e.args}")


@bot.tree.command(name='join', description='Join a ranked lobby')
async def join(
    itx: discord.Interaction,
    host_user: discord.User,
  ) -> None:
  """ The caller tries to join another user's lobby. """
  joiner_player = get_player(itx.user)
  host_player = get_player(host_user)
  # Try finding and joining the lobby
  try:
    LobbyManager.join_lobby(host_player, joiner_player)
  except Exception as e:
    await itx.response.send_message(f"ERROR: {e.args}", ephemeral=True)
  else:
    debug_print("Lobby joined successfully.")
    await itx.response.send_message(
      f"{joiner_player.display_name} joined {host_player.display_name}'s lobby"\
        "\n-# Use `/result` to report the result of each match."
    )


@bot.tree.command(name='leave', description="Leave the lobby you're in")
async def leave(itx: discord.Interaction) -> None:
  """ The caller tries to leave their current lobby """
  player = get_player(itx.user)
  # Try finding and leaving the lobby
  try:
    LobbyManager.leave_lobby(player)
  except Exception as e:
    await itx.response.send_message(f"ERROR: {e.args}", ephemeral=True)
  else:
    debug_print("Lobby exited successfully.")
    await itx.response.send_message(f"{player.display_name} left a lobby")


@bot.tree.command(name='result', description='Report the result of a match')
async def result(
    itx: discord.Interaction,
    match_result: Literal['I won', 'I lost', 'Draw', 'Undo'],
  ) -> None:
  """ A player reports the result of their match.
      If `match_result` == "Undo" then only update the match log,
      otherwise update each player's Elo. """
  discord_account = itx.user
  this_player = get_player(discord_account)
  try:
    # Fetch the player's lobby and the opponent Player; exit if they aren't found
    lobby = LobbyManager.find_lobby(this_player)
    opponent = next((player for player in lobby['players'] if player != this_player), None)
    if opponent is None:
      await itx.response.send_message("You're in an empty lobby.", ephemeral=True)
      return
    # Determine the winner and report the result
    if match_result == "I won":
      winner = this_player
      loser = opponent
    else:
      winner = opponent
      loser = this_player
    # Handle Undo
    if match_result == 'Undo':
      LobbyManager.update_match_log(lobby['region'], lobby['platform'], winner, loser, undo=True)
      result_text = "Noted undo (bot has to be reloaded for it to take effect)."
    else:
      result_text = LobbyManager.report_match_result(winner, draw=(match_result=="Draw"))
    await itx.response.send_message(result_text, ephemeral=False)
  except Exception as e:
    await itx.response.send_message(f"ERROR: {e.args}", ephemeral=True)
    return


@app_commands.default_permissions(ban_members=True)
@bot.tree.command(name='ban_ranked', description='Ban a player from the ranked bot')
async def ban_ranked(
    itx: discord.Interaction,
    user: discord.User,
  ) -> None:
  """ Ban a user from using the ranked bot. """
  this_player = get_player(user)
  this_player.banned = True
  await itx.response.send_message(
    f"{this_player.display_name} got banned lmao", ephemeral=True
  )


@bot.tree.command(name='list_lobbies', description='List the lobbies')
async def list_lobbies(itx: discord.Interaction) -> None:
  """ Display a list of the current opened lobbies. """
  text = LobbyManager.list_lobbies()
  if text:
    await itx.response.send_message(text, ephemeral=True)
  else:
    await itx.response.send_message("There are no lobbies open.", ephemeral=True)


@bot.tree.command(name='leaderboard', description='Display a leaderboard for the region/platform')
async def leaderboard(
    itx: discord.Interaction,
    region: Literal['NA', 'EU', 'ASIA', 'SA', 'MEA'],
    platform: Literal['Steam', 'PS'], # use "Steam", as "PS" ~= "PC" visually
  ) -> None:
  """ Display a leaderboard for the region/platform. """
  if platform == 'Steam':
    platform = 'PC'
  try:
    players = [player for player in PlayerManager.players.values()
               if (region,platform) in player.records
               and not player.banned]
    if players:
      def sort_by_elo(player: Player):
        return player.records[(region,platform)]['elo']
      players.sort(key=sort_by_elo, reverse=True)
      lines = []
      for player in players:
        record = player.records[(region,platform)]
        elo = record['elo']
        elo_prefix = '~' if record['matches_total'] < 30 else ' '
        lines.append(f"{elo_prefix}{int(elo):>4} │ {player.display_name}")
      header = "``` Elo  │ Player\n"\
                  "──────┼─────────────────\n"
      output = header + '\n'.join(lines) + "```"
      await itx.response.send_message(output, ephemeral=True)
    else:
      await itx.response.send_message(
        'Nobody has played in this region/platform.', ephemeral=True
      )
  except Exception as e:
    debug_print(e.args)


##############
# ! commands #
##############


# ping pong test
@bot.command(name='ping')
async def ping(ctx: discord.ext.commands.context.Context) -> None:
  """ A simple ping-pong test to see if the bot is online. """
  await ctx.send("Pong!")


###################
# Other functions #
###################


def get_player(user: discord.member.Member) -> Player:
  """ Resolve a Player from their Discord user.
      Use this to interface with PlayerManager players, as it can update
      the Player's display name. """
  user_id = str(user.id)
  player: Player = PlayerManager.get_player(user_id)
  # Resolve and save display name
  if not player.display_name:
    name = user.global_name if user.global_name else user.display_name
    player.display_name = name
  return player


async def handle_autoreply(msg: discord.message.Message) -> None:
  """ Apply all automatic replies to a message. """
  text: str = msg.content
  # Beggars
  if re.search(r'(final|last).{0,20}achiev', text)\
      or re.search(r'help.{0,40}achiev', text)\
      or ('tourn' in text and 'achiev' in text):
    # Skip users who have played at least one match
    player = get_player(msg.author)
    if not any(record["matches_total"] > 0
               for record in player.records.values()):
      await msg.channel.send(f"You probably won't find anyone to help with getting the tournament achievement here {msg.author.mention}")


@async_cache
async def bot_fetch_user(user_id: int) -> discord.User:
  """ Fetch a user and cache the result. """
  debug_print("Fetching user:", user_id)
  user = await bot.fetch_user(user_id)
  return user


if __name__ == "__main__":
  asyncio.run(main())
