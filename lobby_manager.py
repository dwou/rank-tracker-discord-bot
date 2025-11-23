""" Module defining the LobbyManager class. """

import time
import asyncio
import os
from players import Player, PlayerManager
from basic_functions import debug_print, create_elo_function


class LobbyManager():
  """ A singleton class to manage lobbies. """
  ELO_FUNCTION = create_elo_function(K=20, diff=100, xtimes=2)
  KEEPALIVE_DURATION = 30 * 60  # seconds; initial time to keep a lobby alive for
  REFRESH_DURATION = 3 * 60     # seconds; time to keep a lobby alive without activity
  COOLDOWN_TIME = 30            # seconds; minimum time between lobby actions (match results)
  lobbies: dict[int, dict] = {} # lobby ID -> {}
  # `lobbies`: key identifier(1,2,3,...) -> dict:
  #   "ID": int,
  #   "region":_, "platform":_,
  #   "start_time":_, "last_interaction":_,
  #   "players": set[Player],
  #   "records": dict[Player, dict[W/L/D/matches_total -> int]]
  #   "invited_players": set[Player]

  @classmethod
  async def __lobby_autocloser(cls, lobby: dict) -> None:
    """ Periodically check if it's time to close a lobby based on last_interaction."""
    sleep_duration = cls.KEEPALIVE_DURATION
    start_time = time.time()
    while True:
      await asyncio.sleep(sleep_duration)
      now = time.time()
      sleep_duration = \
        max(
          lobby['last_interaction'] + cls.REFRESH_DURATION, # since the last refresh
          start_time + cls.KEEPALIVE_DURATION, # since lobby creation
        ) - now
      if sleep_duration < 0:
        debug_print(f"Closing lobby #{lobby['ID']}.")
        del cls.lobbies[lobby['ID']]
        return

  @classmethod
  async def new_lobby(cls,
      player: Player,
      region: str,
      platform: str,
      do_not_autoclose: bool=False
    ) -> dict:
    """ Create lobby if player not already in a lobby; return lobby.
        Raise ValueError if `player` is already in a lobby on this platform.
        Raise PermissionError if `player` is banned. """
    if player.banned:
      raise PermissionError("Player is banned from ranked.")

    # Check if the player is already in a lobby.
    for lobby in cls.lobbies.values():
      if player in lobby["players"]:
        raise ValueError(f"Player {player.display_name} is already in a lobby.")

    # Make sure the player has a record with this region+platform.
    _ = player.get_record(region, platform)

    # Find a free lobby ID and create a lobby using it.
    for lobby_id in range(1,1000):
      if lobby_id not in cls.lobbies:
        now = time.time()
        lobby = {
          "ID": lobby_id,
          "region": region,
          "platform": platform,
          "start_time": now,
          "last_interaction": now,
          "players": {player,},
          "records": { # keep a temporary match result record for each player
            player: {'matches_total': 0, 'W': 0, 'L': 0, 'D': 0},
          },
          "invited_players": {player,},
        }
        cls.lobbies[lobby_id] = lobby

        # Spawn a task to automatically close the lobby.
        if not do_not_autoclose:
          asyncio.create_task(cls.__lobby_autocloser(lobby))
        return lobby

  @classmethod
  def update_lobby(cls, lobby: dict) -> None:
    """ Refresh a lobby's last_interaction time. """
    now = time.time()
    lobby['last_interaction'] = now

  @classmethod
  def find_lobby(cls, player: Player) -> dict:
    """ Find the first lobby `player` is in and return it.
        Raise ValueError if the player isn't in a lobby. """
    for lobby in cls.lobbies.values():
      if player in lobby['players']:
        return lobby
    raise ValueError("Player not in a lobby.")

  @classmethod
  def invite_to_lobby(cls, host: Player, guest: Player) -> None:
    """ Mark a lobby as having had invited `invitee`. """
    lobby = cls.find_lobby(host)
    lobby['invited_players'].add(guest)

  @classmethod
  def join_lobby(cls, host: Player, joiner: Player) -> None:
    """ Add `player` to a host's lobby. Don't check platform or region.
        Raise ValueError if lobby is full, doesn't exist, already has `player`,
        or if the player is in another lobby.
        Raise PermissionError if the player is uninvited or banned. """
    if joiner.banned:
      raise PermissionError("You're banned from ranked.")

    # Find the host's lobby.
    try:
      lobby = cls.find_lobby(host)
    except ValueError as e:
      raise ValueError(f"Host \"{host.display_name}\" isn't in a lobby.") from e

    # Check if joiner is aleady in the lobby.
    if joiner in lobby['players']:
      raise ValueError("You're already in this lobby.")

    # Check if joiner is in another lobby.
    for lobby2 in cls.lobbies.values():
      if joiner in lobby2['players'] and lobby2 != lobby:
        raise ValueError("You're already in another lobby (use `/leave` to leave).")

    # Check if lobby is full.
    if len(lobby['players']) > 1:
      raise ValueError("Host lobby is full (wait or make a new one).")

    # Check if joiner is invited.
    if joiner not in lobby['invited_players']:
      raise PermissionError("You haven't been invited to this lobby (the host has to `/invite` you).")

    # Add the joiner to the lobby and update the lobby.
    lobby['players'].add(joiner)
    lobby['records'][joiner] = {'matches_total': 0, 'W': 0, 'L': 0, 'D': 0}
    cls.update_lobby(lobby)

  @classmethod
  def leave_lobby(cls, player: Player) -> None:
    """ Remove `player` from their lobby.
        Raise ValueError if the player isn't found in a lobby. """
    try:
      lobby = cls.find_lobby(player)
    except ValueError:
      raise ValueError("Player not in a lobby.")
    lobby['players'].remove(player)
    del lobby['records'][player]
    cls.update_lobby(lobby)
    # Do not manually close an empty lobby - let close automatically

  @classmethod
  def report_match_result(cls,
      winner: Player,
      draw: bool = False,
      log_result: bool = True
    ) -> str:
    """ Update the W/L/D of both players in the lobby and update their Elos.
        Return a formatted string representing the match results.
        `winner` can be either player in a draw.
        Raise RuntimeError if the lobby is still on cooldown. """
    lobby = cls.find_lobby(winner)
    region = lobby['region']
    platform = lobby['platform']

    # Check if lobby is still on cooldown.
    now = time.time()
    wait_duration = lobby['last_interaction'] + cls.COOLDOWN_TIME - now
    if wait_duration > 0:
      raise RuntimeError(
        f"Can't update lobby: the lobby is on cooldown for {wait_duration:.1f} seconds."
      )

    # Update the lobby records.
    # Let Player p1 be the winner, and p2 the loser.
    PlayerManager.should_save = True
    p1,p2 = None,None
    if not draw:
      for player,record in lobby['records'].items():
        record['matches_total'] += 1
        if player == winner:
          record['W'] += 1
          p1 = player
        else:
          record['L'] += 1
          p2 = player
    else:
      for player,record in lobby['records'].items():
        record['matches_total'] += 1
        record['D'] += 1
        if p1 is None:
          p1 = player
        elif p2 is None:
          p2 = player

    # Fetch current Elos.
    p1_old_elo = p1.get_elo(region, platform)
    p2_old_elo = p2.get_elo(region, platform)

    # Make sure p1 has the lower elo if there's a draw (for displaying elo change).
    if draw:
      if p1_old_elo > p2_old_elo:
        p1,p2 = p2,p1
        p1_old_elo = p1.get_elo(region, platform)
        p2_old_elo = p2.get_elo(region, platform)

    # Calculate Elos and update both players.
    result = cls.ELO_FUNCTION(p1_old_elo, p2_old_elo, p1_wins=(0.5 if draw else 1))
    p1_new_elo = p1_old_elo + result['p1_gain']
    p2_new_elo = p2_old_elo + result['p2_gain']
    p1.records[(region, platform)]['elo'] = p1_new_elo
    p2.records[(region, platform)]['elo'] = p2_new_elo
    p1.records[(region, platform)]['matches_total'] += 1
    p2.records[(region, platform)]['matches_total'] += 1

    # Log the result.
    if log_result:
      cls.update_match_log(region, platform, p1, p2, draw=draw)

    # Format the return the results string.
    result_text = \
      f"[{'D' if draw else 'W'}] {p1.display_name} :green_square: {int(p1_old_elo)} **(+{round(result['p1_gain'])})** ➜ __{int(p1_new_elo)}__"\
      f"\n[{'D' if draw else 'L'}] {p2.display_name} :red_square: {int(p2_old_elo)} **({round(result['p2_gain'])})** ➜ __{int(p2_new_elo)}__"
    return result_text

  @classmethod
  def update_match_log(cls,
      region: str,
      platform: str,
      winner: Player,
      loser: Player,
      draw: bool = False,
      undo: bool = False,
    ) -> str:
    """ Create a timestamped log entry in 'match_log.csv'. """
    this_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(this_dir, "match_log.csv")
    with open(file_path, 'a+', encoding='u8') as f:
      f.write(
        ','.join([
          str(int(time.time())),        # timestamp
          region,                       # region
          platform,                     # platform
          winner.ID,                    # winner ID
          loser.ID,                     # loser ID
          'Undo' if undo else str(draw) # draw ("True", "False", "Undo")
        ]) + '\n'
      )

  @classmethod
  def list_lobbies(cls) -> str:
    """ List each lobby and the players in each. """
    output = ""
    for lobby in cls.lobbies.values():
      output += f'#{lobby['ID']} ({lobby['region']}-{lobby['platform']}): '
      output += ', '.join([player.display_name for player in lobby['players']])
      output += '\n'
    return output
