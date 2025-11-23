""" Module to recalculate elo during bot downtime - must be run manually. """
assert __name__ == "__main__"

import re
import asyncio

from players import PlayerManager
from lobby_manager import LobbyManager


def get_matches() -> dict:
  """ Read and format match_log.csv, and return the result. """
  with open("match_log.csv", 'r', encoding='u8') as f:
    lines = f.read().splitlines()
  pattern = r'(?P<timestamp>\d+),(?P<region>\w+),(?P<platform>\w+),'\
            r'(?P<winner_id>\d+),(?P<loser_id>\d+),(?P<result>\w+)'
  formatted_groups = []
  for line in lines:
    groups = re.match(pattern, line).groupdict()
    formatted_groups.append(groups)
  return formatted_groups


async def main():
  """ Do all the stuff. """
  # Set up the PlayerManager and LobbyManager classes.
  PlayerManager.initialize()
  LobbyManager.KEEPALIVE_DURATION = 10
  LobbyManager.REFRESH_DURATION = 10
  LobbyManager.COOLDOWN_TIME = 0

  # Clear all Player records.
  for player in PlayerManager.players.values():
    player.records = {}

  # Simulate each match, creating a new 1-match lobby for each match.
  matches = get_matches()
  for match in matches:
    # Skip "Undo" "matches".
    if match['result'] == 'Undo':
      continue

    # Get players. Suppose that the host is the winner and the guest is the loser.
    host = winner = PlayerManager.get_player(match['winner_id'])
    guest = PlayerManager.get_player(match['loser_id'])

    # Skip matches where either player is banned.
    if host.banned or guest.banned:
      continue

    # Set up lobby.
    lobby = await LobbyManager.new_lobby(
      host,
      match['region'],
      match['platform'],
      do_not_autoclose=True
    )
    LobbyManager.invite_to_lobby(host, guest)
    LobbyManager.join_lobby(host, guest)

    # Report the match results.
    LobbyManager.report_match_result(
      winner,
      draw=(match['result']=="True"),
      log_result = False
    )

    # Close the lobby.
    del LobbyManager.lobbies[lobby['ID']]

  # Save the new data.
  PlayerManager.save_to_file(backup=True)


asyncio.run(main())
