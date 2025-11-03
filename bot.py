
# Implemented:
#  Near-full Discord integration (idk how to deploy/update)
#  Complete data saving(+backup) and loading system
#  (semi-Automatic) Discord user ranked account creation
#
# Not (yet) implemented:
#  Automatic backups (or anything time- or delay-based)
#  A working lobby and Elo system
#  A customized ping system based on region/platform/Elo
#  API rate limiter (but shouldn't be a problem)

from os import getenv
import re
from typing import Literal

import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

#from helper_functions import *
from _players import *
from basic_functions import *

# TODO: test permissions
# needs '268536832' permissions (I think)

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

# Name Rules: (unnecessary?)
#  case insensitive, forced lowercase
#  Rules: 2-32 length; _ . a-z 0-9 allowed; unique; no consecutive ".."
#  >>> valid_name_pattern = r'(?!.*?\.\.)([a-z0-9_\.]{2,32})'


def get_player(user: discord.member.Member) -> Player:
  """ Use this to interface with PlayerManager players, as it can update
      the Player's display name """
  player: Player = PlayerManager.get_player(user.id)
  # Resolve and cache display name if it's not defined
  if not player.display_name:
    player.display_name = user.global_name #display_name
  return player


###############
# Main/global #
###############


# get "intents" (incoming messages, reactions etc) and create the bot
intents = discord.Intents.default()
intents.message_content = True  # see (incoming messages'?) content
bot = commands.Bot(command_prefix="!", intents=intents)

def main():
  global bot
  PlayerManager.initialize()
  load_dotenv()
  bot.run(getenv("DISCORD_TOKEN"))


##################
# Events/intents #
##################


@bot.event
async def on_ready() -> None:
  await bot.tree.sync()
  debug_print(f"{bot.user} is online!")


@bot.event
async def on_message(msg: discord.message.Message) -> None:
  """ Handle new messages """
  # Drop DMs
  if not msg.guild:
    return

  #text: str = msg.content
  is_bot: bool = msg.author.bot
  #is_admin: bool = msg.author.guild_permissions.administrator

  # Print message and resolve mentioned users/roles/channels
  await pretty_print_message(msg, to_resolve=True)

  # Ignore bots' messages
  if is_bot:
    return

  # Handle automatic replies
  responded: bool = await handle_autoreply(msg)

  # Execute ! commands
  await bot.process_commands(msg)


##################
# Slash commands #
##################


@commands.has_permissions(administrator=True)
@bot.tree.command(name='save', description='Saves player data')
async def save(
    itx: discord.Interaction,
    backup: bool
  ) -> None:
  PlayerManager.save_to_file(backup=backup)
  debug_print('Saved PlayerManager.')
  await itx.response.send_message(f'Saved.', ephemeral=True)


@bot.tree.command(name='playerdata', description='Prints player data')
async def playerdata(
    itx: discord.Interaction,
    user_at: str,
  ) -> None:
  debug_print(user_at)
  response = ""
  if match := re.match(r'<@(\d+)>', user_at):
    ID = match.group(1)
    try:
      mention_user = await bot.fetch_user(ID)
    except Exception as e:
      response = f"{type(e)}: {e.args}"
    else:
      player = get_player(mention_user)
      response = player.pretty_print()
  else:
    response = "Invalid syntax: " + user_at
  await itx.response.send_message(response, ephemeral=True)


@bot.tree.command(name='help', description="Shows a description of a given command")
async def help(
    itx: discord.Interaction,
    command: Literal['/ranked', '/playerdata', '/save', '!ping'],
  ) -> None:
  match command:
    case '/ranked':
      to_print = "Open a 1v1 ranked lobby given region and platform."\
        "\nLobbies must be updated periodically using !{win,lose,draw} <lobby number>"
    case '/playerdata':
      to_print = "Privately display a overview of a user's ranked profile, using:"\
        "\"/playerdata @user\""
    case '/save':
      to_print = "[admin-only] Manually save the PlayerManager data."
    case '!ping':
      to_print = "A simple ping-pong test to see if the bot is online."
    case _:
      to_print = "Command not found."
  await itx.response.send_message(to_print, ephemeral=True)


@bot.tree.command(name='ranked', description='Opens a ranked session')
async def ranked(
    itx: discord.Interaction,
    region: Literal['NA','EU','Asia'],
    platform: Literal['Steam', 'PS'],
  ) -> None:
  if platform == 'Steam':
    platform = 'PC'
  discord_account_ID = itx.user.id
  this_player = get_player(itx.user)
  lobby_ID = PlayerManager.new_lobby(this_player, region, platform)
  if lobby_ID is None:
    await itx.response.send_message(
      "Error: you're already in a lobby.",
      ephemeral=True
    )
    return
  await itx.response.send_message(
    f"<@{discord_account_ID}> just opened a ranked lobby!\n"
      + this_player.pretty_print(),
    ephemeral=False
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


async def pretty_print_message(
    msg: discord.message.Message,
    to_resolve: bool = False
  ) -> None:
  """ Print the message and resolve mentioned users/roles """
  raw_text: str = msg.content
  is_bot: bool = msg.author.bot
  is_admin: bool = msg.author.guild_permissions.administrator
  pretty_text: str = raw_text
  # iterate through each "<...>""  in the message, resolve, and replace
  # TODO: correctly resolve all these (or all) cases
  for prefix,digits in re.findall(r'<(@|@&|#)(\d{1,20})>', raw_text):
    raw_match = f'<{prefix}{digits}>'
    Type = {'@': 'user', '@&': 'role', '#': 'channel'}[prefix]
    match Type:
      case 'role':
        pretty_fragment = '@[a role]'
      case 'user':
        if to_resolve:
          mention_username = (await bot.fetch_user(digits)).display_name
          pretty_fragment = f"@[{mention_username}]"
        else:
          pretty_fragment = '@[a user]'
      case 'channel':
        pretty_fragment = '#[a channel]'
      case _:  # no match
        debug_print(f"Unknown match: {raw_match}")
        continue
    pretty_text = pretty_text.replace(raw_match, pretty_fragment)
  title = 'bot' if is_bot else ('admin' if is_admin else 'user')
  debug_print(f'[{title} {msg.author.display_name}]: {pretty_text}')


async def handle_autoreply(msg: discord.message.Message) -> bool:
  """ apply all the functions that automatically reply to a message.
      Return True if there is any match """
  text: str = msg.content
  author: discord.member.Member = msg.author.mention
  beggar_pattern = r'(?=(.{0,40}tourn.{0,30})|(help|final|last)).{0,30}achiev'
  if re.search(beggar_pattern, text):
    # TODO: check if it's their first 3 messages
    debug_print('!!! Beggar Detected !!!')
    await msg.channel.send(f"You probably won't find anyone to help with getting the tournament achievement here {msg.author.mention}")
  else: # No matches
    return False
  return True


if __name__ == "__main__":
  main()
