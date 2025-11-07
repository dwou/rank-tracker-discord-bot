import time
import asyncio
from basic_functions import *

class LobbyManager():
  elo_function = create_elo_function(K=20, diff=100, xtimes=2)
  keepalive_duration = 30 * 60 # seconds; initial time to keep a lobby alive for
  refresh_duration = 3 * 60 # seconds; time to keep a lobby alive without activity
  lobbies: dict[int, dict] = dict() # lobby ID -> {}
  # `lobbies`: key identifier(1,2,3,...) -> Dict:
  #   "ID": int,
  #   "region":_, "platform":_,
  #   "start_time":_, "last_interaction":_,
  #   "players": set[Player],
  #   "records": dict[player, dict[W/L/D -> int]]
  #   "invited_players": set[Player]

  @classmethod
  async def __lobby_autocloser(cls, lobby: dict) -> None:
    """ Periodically check if it's time to close a lobby based on last_interaction."""
    sleep_duration = cls.keepalive_duration
    start_time = time.time()
    while True:
      await asyncio.sleep(sleep_duration)
      now = time.time()
      sleep_duration = \
        max(
          lobby['last_interaction'] + cls.refresh_duration, # since the last refresh
          start_time + cls.keepalive_duration, # since lobby creation
        ) - now
      if sleep_duration < 0:
        debug_print(f"Closing lobby #{lobby['ID']}.")
        del cls.lobbies[lobby['ID']]
        return

  @classmethod
  async def new_lobby(cls, player: Player, region: str, platform: str) -> dict:
    """ Create lobby if player not already in a lobby; return lobby.
        Raise ValueError if `player` is already in a lobby on this platform.
        Raise PermissionError if `player` is banned. """
    if player.banned:
      raise PermissionError("Player is banned from ranked.")
    # Check if they're already in a lobby
    for lobby in cls.lobbies.values():
      if player in lobby["players"]:
        raise ValueError(f"Player {player.display_name} is already in a lobby.")
    # Make sure they have a record with this region+platform
    _ = player.get_record(region, platform)
    # Find a free lobby ID and create a lobby using it
    for lobby_ID in range(1,1000):
      if lobby_ID not in cls.lobbies:
        now = time.time()
        lobby = {
          "ID": lobby_ID,
          "region": region,
          "platform": platform,
          "start_time": now,
          "last_interaction": now,
          "players": {player,},
          "records": { # keep a temporary match result record for each player
            player: {'W': 0, 'L': 0, 'D': 0},
          },
          "invited_players": set(),
        }
        cls.lobbies[lobby_ID] = lobby
        debug_print(f'Created lobby #{lobby_ID}')
        # Spawn a task to automatically close the lobby
        asyncio.create_task(cls.__lobby_autocloser(lobby))
        return lobby

  @classmethod
  def update_lobby(cls, lobby: dict) -> None:
    """ Refresh a lobby's last_interaction time. """
    now = time.time()
    debug_print(f"Lobby #{lobby['ID']} updating last_interaction to {now=}")
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
  def invite_to_lobby(cls, host: Player, invitee: Player) -> None:
    """ Mark a lobby as having had invited `invitee`. """
    lobby = cls.find_lobby(host)
    lobby['invited_players'].add(invitee)

  @classmethod
  def join_lobby(cls, host: Player, joiner: Player) -> None:
    """ Add `player` to a host's lobby. Don't check platform or region.
        Raise ValueError if lobby is full, doesn't exist, already has `player`,
        or if the player is in another lobby.
        Raise PermissionError if the player is uninvited or banned. """
    if joiner.banned:
      raise PermissionError("You're banned from ranked.")
    # Find the host's lobby
    try:
      lobby = cls.find_lobby(host)
    except ValueError as e:
      raise ValueError("Host not in a lobby.") from e
    # Check if player is aleady in the lobby
    if joiner in lobby['players']:
      raise ValueError("You're already in this lobby.")
    # Check if player is in another lobby
    for lobby2 in cls.lobbies.items():
      if joiner in lobby2['players'] and lobby2 != lobby:
        raise ValueError(f"You're already in another lobby (use \"/leave\").")
    # Check if lobby is full
    if len(lobby['players']) > 1:
      raise ValueError(f"Host lobby is full (wait or make a new one).")
    # Check if player is invited
    if joiner not in lobby['invited_players']:
      raise PermissionError(f"You haven't been invited to this lobby (the host has to /invite you).")
    # Add the player and update the lobby
    lobby['players'].add(joiner)
    lobby['records'][joiner] = {'W': 0, 'L': 0, 'D': 0}
    cls.update_lobby(lobby)

  @classmethod
  def leave_lobby(cls, player: Player) -> None:
    """ Remove `player` from their lobby. """
    lobby = cls.find_lobby(player)
    lobby['players'].remove(player)
    del lobby['records'][player]
    cls.update_lobby(lobby)
    # Do not manually close an empty lobby - let close automatically

  @classmethod
  def report_match_result(cls, winner: Player, draw: bool = False) -> None:
    """ Update the W/L/D of both players in the lobby and update their Elos.
        `winner` can be either player in a draw. """
    lobby = cls.find_lobby(winner)
    # Let Player p1 be the winner, and p2 the loser
    p1,p2 = None,None
    if not draw:
      for player,record in lobby['records'].items():
        if player == winner:
          record['W'] += 1
          p1 = player
        else:
          record['L'] += 1
          p2 = player
    else:
      for player,record in lobby['records'].items():
        record['D'] += 1
        if p1 is None:
          p1 = player
        else:
          p2 = player
    # Update the Elos
    p1_elo = p1.get_elo(region, platform)
    p2_elo = p2.get_elo(region, platform)
    result = cls.elo_function(p1_elo, p2_elo)
    p1[(region, platform)] += result['p1_gain']
    p2[(region, platform)] += result['p2_gain']
