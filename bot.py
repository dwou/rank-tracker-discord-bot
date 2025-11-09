# Use this invite link (it displays permissions before you accept):
#  "https://discord.com/oauth2/authorize?client_id=1429136363151950008&permissions=2048&integration_type=0&scope=bot+applications.commands

# Implemented:
#   Seemingly complete lobby and Elo system
#   Complete data saving(+backup +autosaving) and loading system
#   (semi-Automatic) Discord user ranked account creation
#
# Not (yet) implemented:
#   A customized ping system based on region/platform/Elo (not useful for now)
#   API rate limiter (but shouldn't be a problem)

# TODO: test on Windows
# TODO: process match log to re-compute Elo upon startup (including using "undo")
# TODO: figure out how to deploy/update

from os import getenv
import re
from typing import Literal
from functools import cache
import asyncio

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

from _players import *
from LobbyManager import *
from basic_functions import *

AUTOSAVE = True
AUTOSAVE_BACKUPS = False # whether to back up previous data while autosaving
AUTOSAVE_PERIOD = 120 #1 * 60 # (seconds) autosave periodically
report_str = "Report bugs to /DWouu." # string to append to certain messages

# NOTES: Types & naming conventions, Functions, Data
'''
"msg": discord.message.Message  # a Discord message
  .channel
    .send()                # send a message
  .content: str            # the message's content
  .author                  # the author, a Member
discord.member.Member
  .guild_permissions
    .administrator: bool   # is an admin
  .mention: str?           # the username
  .bot: bool               # is a bot
  .display_name
  .global_name             # display_name but sometimes returns None)
"itx" discord.Interaction  # for slash commands (among other things?)
  .response
    .send_message()
  .user: Member            # the message sender
  .channel
"ctx" (discord.ext.)commands.context.Context  # it's like a Member
  .send                    # send a message; different from channel.send()?
'''


###############
# Main/global #
###############


# get "intents" (incoming messages, reactions etc) and create the bot
intents = discord.Intents.default()
intents.message_content = True  # see (incoming messages'?) content
bot = commands.Bot(command_prefix="!", intents=intents)

async def main():
  global bot
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
  await bot.tree.sync()
  debug_print(f"{bot.user} is online!")


@bot.event
async def on_message(msg: discord.message.Message) -> None:
  """ Handle new messages. """
  # Drop DMs
  if not msg.guild:
    return

  # Print message
  formatted_msg: str = await format_message(msg, Format="%t [%d]: %f")
  debug_print(formatted_msg)

  # Ignore bots' messages
  is_bot: bool = msg.author.bot
  if is_bot:
    return

  # Handle automatic replies
  responded: bool = await handle_autoreply(msg)

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


@app_commands.default_permissions(administrator=True)
@bot.tree.command(name='save', description='Saves player data')
async def save(
    itx: discord.Interaction,
    backup: bool,
  ) -> None:
  PlayerManager.save_to_file(backup=backup)
  debug_print('Saved PlayerManager.')
  await itx.response.send_message(f'Saved.', ephemeral=True)


@bot.tree.command(name='playerdata', description='Prints player data')
async def playerdata(
    itx: discord.Interaction,
    user: discord.User,
  ) -> None:
  player = get_player(user)
  response = player.get_summary()
  await itx.response.send_message(response, ephemeral=True)


@bot.tree.command(name='help', description="Shows a description of a given command")
async def help(
    itx: discord.Interaction,
  ) -> None:
  text = """-# Note: "lobby" here refers to the object that this Discord bot keeps track of internally.
```
/ranked <region> <platform> <ping_users={True|False}>
        Open a ranked lobby and optionally ping users in the region/platform.
        The lobby must be periodically updated using /result.

/invite <user>
        Allow a player to join your lobby.

/join
        Join a lobby (you need to be invited first).

/leave
        Leave a lobby.

/result {I won|I lost|Draw|Undo}
        Report the result of a match (must be in a lobby with the other player).
        Note: "Undo" doesn't take effect until after the bot is restarted.

/playerdata <user>
        Display the ranked data of a user.

/save <backup={True|False}>
        [admin-only] Manually save the PlayerManager data.

!ping
        A simple ping-ping test to check if the bot is online.```
"""
  await itx.response.send_message(text, ephemeral=True)


@bot.tree.command(name='ranked', description='Opens a ranked session')
async def ranked(
    itx: discord.Interaction,
    region: Literal['NA', 'EU', 'Asia', 'SA', 'MEA'],
    platform: Literal['Steam', 'PS'], # use "Steam", as "PS" ~= "PC" visually
    ping_users: Literal['Ping users', "Don't ping users"],
  ) -> None:
  if platform == 'Steam':
    platform = 'PC'
  discord_account = itx.user
  this_player = get_player(discord_account)
  # Try making a new lobby for this player and proceed if a new lobby is made
  try:
    lobby = await LobbyManager.new_lobby(this_player, region, platform)
  except ValueError as e:
    debug_print(e.args)
    await itx.response.send_message(
      f"ERROR: {e.args}",
      ephemeral=True
    )
    return
  if ping_users == "Ping users":
    role_name = f"{region}-T7-{platform}"
    role = discord.utils.get(itx.guild.roles, name=role_name)
    role_str = f"<@&{role.id}> "
  else:
    role_str = ''

  # TODO: which looks better?
  header = f"{role_str}:speaking_head::mega: <@{discord_account.id}> just opened a ranked lobby!\n\n"
  #header = f":rotating_light: <@{discord_account_ID}> just opened a ranked lobby :rotating_light:\n\n"
  debug_print(header)
  await itx.response.send_message(
      header
      + this_player.get_summary()
      + f"\n_-# {report_str}_",
    ephemeral=False
  )
  await itx.followup.send("Don't forget to `/invite` people.", ephemeral=True)


@bot.tree.command(name='invite', description='Invites another user to a ranked session')
async def invite(
    itx: discord.Interaction,
    invited_user: discord.User,
  ) -> None:
  try:
    host = itx.user
    host_player = get_player(host)
    invitee_player = get_player(invited_user)
    LobbyManager.invite_to_lobby(host_player, invitee_player)
    text = f"<@{host.id}> invited <@{invited_user.id}>"\
      "\n-# use `/join` to join their lobby"
    await itx.response.send_message(text)
  except Exception as e:
    await itx.response.send_message(f"ERROR: {e.args}")


@bot.tree.command(name='join', description='Join a ranked lobby')
async def join(
    itx: discord.Interaction,
    host_user: discord.User,
  ) -> None:
  """ The caller tries to join the lobby of `at_user` """
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
async def leave(
    itx: discord.Interaction,
  ) -> None:
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
    result: Literal['I won', 'I lost', 'Draw', 'Undo'],
  ) -> None:
  """ A player reports the result of their match.
      If result == "Undo" then only update the match log, otherwise try to
      update each player's Elo. """
  discord_account = itx.user
  this_player = get_player(discord_account)
  try:
    # Fetch the player's lobby and the opponent Player; exit if they aren't found
    lobby = LobbyManager.find_lobby(this_player)
    opponent = next((player for player in lobby['players'] if player != this_player), None)
    if opponent is None:
      await itx.response.send_message(f"You're in an empty lobby.", ephemeral=True)
      return
    # Determine the winner and report the result
    if result == "I won":
      winner = this_player
      loser = opponent
    else:
      winner = opponent
      loser = this_player
    # Handle Undo
    if result == 'Undo':
      LobbyManager.update_match_log(lobby['region'], lobby['platform'], winner, loser, undo=True)
      result_text = "Noted undo (bot has to be reloaded for it to take effect)."
    else:
      result_text = LobbyManager.report_match_result(winner, draw=(result=="Draw"))
    await itx.response.send_message(result_text, ephemeral=False)
  except Exception as e:
    await itx.response.send_message(f"ERROR: {e.args}", ephemeral=True)
    return


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


##############
# ! commands #
##############


# ping pong test
@bot.command(name='ping')
async def ping(ctx: discord.ext.commands.context.Context) -> None:
  await ctx.send("Pong!")


###################
# Other functions #
###################


def get_player(user: discord.member.Member) -> Player:
  """ Resolve a Player from their Discord user.
      Use this to interface with PlayerManager players, as it can update
      the Player's display name. """
  user_ID = str(user.id)
  player: Player = PlayerManager._get_player(user_ID)
  # Resolve and save display name
  if not player.display_name:
    name = user.global_name if user.global_name else user.display_name
    player.display_name = name
  return player


async def resolve_at_user(at_user: str) -> discord.User:
  """ Convert at_user (="<@user_ID>") to a User. """
  if match := re.match(r'<@(\d+)>', at_user):
    ID = match.group(1)
    user = await bot_fetch_user(ID)
  else:
    raise ValueError(f"Invalid syntax: `{at_user}` (did you use \"@user\" ?)")
  return user


async def format_message(
    msg: discord.message.Message, # doesn't work with Interactions :(
    Format: str = "[%T %d]: %f", # see `format_map`
    to_resolve: bool = True,
  ) -> None:
  """ Format the message and resolve mentioned users/roles/etc. """
  # Iterate through each "<...>"  in the message, resolve, and replace
  raw_text: str = msg.content
  pretty_text: str = raw_text
  for prefix,digits in re.findall(r'<(@|@&|#)(\d{1,20})>', raw_text):
    raw_match = f'<{prefix}{digits}>'
    Type = {'@': 'user', '@&': 'role', '#': 'channel'}[prefix]
    match Type:
      case 'role':
        pretty_fragment = '@[a role]'
      case 'user':
        if to_resolve:
          mention_username = (await bot_fetch_user(digits)).display_name
          pretty_fragment = f"@[{mention_username}]"
        else:
          pretty_fragment = '@[a user]'
      case 'channel':
        pretty_fragment = '#[a channel]'
      case _:  # no match
        debug_print(f"Unknown match: {raw_match}")
        pretty_fragment = "[???]"
    pretty_text = pretty_text.replace(raw_match, pretty_fragment)

  # Prepare formatting the message
  is_bot: bool = msg.author.bot
  is_admin: bool = msg.author.guild_permissions.administrator
  title = 'bot' if is_bot else ('admin' if is_admin else 'user')
  format_map = {
    "%n": msg.author.name,
    "%g": msg.author.global_name,
    "%d": msg.author.display_name,
    "%c": msg.channel.name,
    "%r": msg.content, # unformatted (raw) content
    "%f": pretty_text,# if content else msg.content, # formatted (given) content
    "%T": title, # full title "bot"|"admin"|"user"
    "%t": title[0], # first letter of `title`
  }

  # Apply the format; substitute in-place
  output = Format
  for key,value in format_map.items():
    output = re.sub(f"({key})", str(value), output)

  return output


async def handle_autoreply(msg: discord.message.Message) -> bool:
  """ Apply all the functions that automatically reply to a message.
      Return True if there is any match. """
  text: str = msg.content
  beggar_pattern = r'(?=(.{0,40}tourn.{0,30})|(help|final|last)).{0,30}achiev'
  if re.search(beggar_pattern, text):
    # Skip users with a ranked record, unless they have 0 total matches recorded
    player = get_player(msg.author)
    print(player.records)
    if not player.records\
        or not any(pair[matches_total] for pair in player.records):
      debug_print('!!! Beggar Detected !!!')
      await msg.channel.send(f"You probably won't find anyone to help with getting the tournament achievement here {msg.author.mention}")
  else: # No matches
    return False
  return True


@async_cache
async def bot_fetch_user(user_ID: int) -> discord.User: # supposed to be int? try using str
  """ Fetch a user and cache the result. """
  print("Fetching user:", user_ID)
  user = await bot.fetch_user(user_ID)
  return user


if __name__ == "__main__":
  asyncio.run(main())
