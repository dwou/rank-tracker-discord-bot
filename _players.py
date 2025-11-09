import os
import re
import json
import time
import asyncio # to autoclose lobbies
from copy import copy
from basic_functions import *
from LobbyManager import *

DEFAULT_ELO = 1000.0 # only used for new Players


class PlayerManager():
  filename: str = None
  players: dict[str, Player] = dict()
  ID_map: dict[str, str] = dict() # curr -> prev; no Discord interface yet

  @classmethod
  def initialize(cls, filename: str = 'data.json'):
    cls.filename = filename
    cls._load_data()

  @classmethod
  def _load_data(cls) -> None:
    """ Load players,ID_map from a file, or create a new file and vars.
        Assume all input data is valid. """
    # Load the file if it exists
    this_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(this_dir, cls.filename)
    if not os.path.isfile(file_path):
      debug_print("No input file found.")
      # use default values for the variables
      return
    with open(file_path, "r") as f:
      json_data = json.load(f)

    # Unpack the players
    for p in json_data['players']:
      debug_print('Reading player:', p)
      ID = p['ID']
      # Deserialize the records
      records = dict()
      for r in p['records']:
        # Move the region and platform from values to keys
        region = r['region']
        platform = r['platform']
        del r['region'], r['platform']
        records[(region, platform)] = r # TODO: make sure it copies
      del p['records'] # use the created `records`, not the loaded one
      cls.players[ID] = Player(**p, records=records)

    # Unpack the ID_map
    for im in json_data['ID_map']:
      debug_print('Reading (IDs):', im)
      ref_ID = im['ref_ID']
      orig_ID = im['orig_ID']
      debug_print(f'{ref_ID} -> {orig_ID}')
      cls.ID_map[ref_ID] = orig_ID

  @classmethod
  def debug_print_players(cls) -> None:
    """ Print all players, for debugging. """
    for player in cls.players.values():
      debug_print(vars(player))

  @classmethod
  def _get_player(cls, ID: str) -> Player:
    """ Fetch a player by their ID; Create them if they don't exist;
        Resolve their ID if it's mapped. Error on a circular pointer chain. """
    checked_IDs = set()
    while ID in cls.ID_map:
      if ID in checked_IDs:
        raise RuntimeError("get_player circular pointer error")
      checked_IDs.add(ID)
      ID = cls.ID_map[ID]
    if ID not in cls.players:
      debug_print(f"Making a new player with {ID=}")
      cls.players[ID] = Player(ID)
    return cls.players[ID]

  @classmethod
  def _serialize(cls) -> Dict:
    """ Create serialized representation of this object, for json """
    epoch_time = int(time.strftime("%s"))
    readable_time = time.strftime("%Y-%m-%d at %T %Z")
    data = {
      "timestamp": [epoch_time, readable_time],
      "ID_map": cls.ID_map,
      "default_elo": DEFAULT_ELO,
      "players": [player._serialize() for player in cls.players.values()],
    }
    return data

  @classmethod
  def save_to_file(cls, backup=False) -> None:
    this_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(this_dir, cls.filename)

    # Back up (rename instead of overwrite) the old data if applicable
    if backup:
      # Rename the current <filename>.json to <filename>-<timestamp>.json
      old_basename = cls.filename[:-5] # strip ".json"
      unix_time = time.strftime("%s")
      backup_name = os.path.join(this_dir, f'{old_basename}-{unix_time}.json')
      if os.path.isfile(file_path):
        os.rename(file_path, backup_name)
      else:
        debug_print("There's nothing to back up.")

    # Save data to file
    data = cls._serialize()
    with open(file_path, 'w') as f:
      json.dump(data, f, indent=2)

  @classmethod
  def remap_ID(cls, curr_ID: str, prev_ID: str) -> None:
    """ Remap one Discord ID to another (in case they lose their account etc).
        Should be restricted to admin-only. """
    cls.ID_map[curr_ID] = prev_ID

  @classmethod
  async def autosave(cls, period: float, backup: bool) -> None:
    # Assume autosaving is enabled if this method is called
    start_time = time.time()
    while True:
      await asyncio.sleep(period)
      cls.save_to_file(backup=backup)


class Player():
  # self.records: map[tuple,dict] =
  #   ('NA','PC'): ("matches_total":int, "elo":float), ...
  def __init__(self,
      ID: str,
      banned: bool = False,
      display_name: str = "",
      records: dict() = None # set to None, because using a mutable default arg is problematic
    ) -> None:
    self.ID = ID
    self.banned = banned
    self.display_name = display_name
    if records:
      self.records = records
    else:
      self.records = dict()

  def get_record(self, region, platform) -> dict:
    """ Fetch and return record. Create one if it doesn't exist. """
    couple = (region, platform)
    if couple not in self.records:
      self.records[couple] = {"matches_total": 0, "elo": DEFAULT_ELO}
    return self.records[couple]

  def get_elo(self, region, platform) -> float:
    return self.get_record(region, platform)['elo']

  def _serialize(self) -> Dict:
    """ Create serialized representation of this object, for saving to json. """
    # tuple cannot be used as a key in json;
    #   move each (region,platform) into the values
    serialized_records = []
    for (region, platform),value in self.records.items():
      # skip empty records
      if value['matches_total'] == 0:
        continue
      this_record = copy(value)
      this_record["region"] = region
      this_record["platform"] = platform
      serialized_records.append(this_record)

    data = {
      "display_name": self.display_name,
      "ID": self.ID,
      "records": serialized_records,
      "banned": self.banned,
    }
    #debug_print("Serialized player data:", data)
    return data

  def get_summary(self) -> None:
    """ Return a string summary of this Player. """
    output = f"-# {self.display_name} has the following records:\n"
    any_found = False
    for (region,platform),record in self.records.items():
      if record['matches_total']:
        # TODO: sort
        output += (f"* {region}-{platform}: **{int(record['elo'])}** Elo, {record['matches_total']} matches\n")
        any_found = True
    if not any_found:
      output += "-# * None, they're new!\n"
    if self.banned:
      output += "and they're BANNED\n"
    output = output.strip()
    return output

