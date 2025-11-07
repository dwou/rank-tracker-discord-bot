import os
import re
import json
import time
import asyncio # to autoclose lobbies
from basic_functions import *
from LobbyManager import *

# in case it has to be adjusted; functionality incomplete
DEFAULT_ELO = 1000.0


class PlayerManager():
  filename: str = None
  players: dict[str, Player] = dict()
  ID_map: dict[str, str] = dict() # curr -> prev
  default_elo: float = None

  @classmethod
  def initialize(cls, filename='players.json'):
    cls.filename = filename
    #cls.players = cls._load_players() # ID -> player
    cls._load_data(filename=filename)

  @classmethod
  def _load_data(cls, filename=None) -> None:
    """ Load players,ID_map from a file, or create a new file and vars.
        Adjust important elo based on DEFAULT_ELO.
        Assume all input data is valid. """
    ## Load the file if it exists
    if filename is None:
      filename = cls.filename
    this_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(this_dir, filename)
    if not os.path.isfile(file_path):
      debug_print("No input file found.")
      cls.default_elo = DEFAULT_ELO
      # use default (empty) values for the other variables
      return
    with open(file_path, "r") as f:
      debug_print('Loading data...')
      json_data = json.load(f)
      debug_print(f"Loaded data: {json_data}")

    ## Unpack the loaded data
    cls.default_elo = json_data['default_elo']
    elo_offset = 0 if DEFAULT_ELO == cls.default_elo \
                 else DEFAULT_ELO - cls.default_elo

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
        r['elo'] += elo_offset
        records[(region, platform)] = r # TODO: make sure it copies
      del p['records'] # use the created record, not the loaded one
      cls.players[ID] = Player(**p, records=records)

    # Unpack the ID_map
    for im in json_data['ID_map']:
      debug_print('Reading (IDs):', im)
      ref_ID = im['ref_ID']
      orig_ID = im['orig_ID']
      debug_print(f'{ref_ID} -> {orig_ID}')
      cls.ID_map[ref_ID] = orig_ID

    cls.default_elo = DEFAULT_ELO # after adjusting loaded values

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
        raise "get_player circular pointer error"
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
      "default_elo": cls.default_elo,
      "players": [player._serialize() for player in cls.players.values()],
    }
    return data

  @classmethod
  def save_to_file(cls, backup=False) -> None:
    # Do nothing if there's no data to save
    if not cls.players:
      debug_print("There's nothing to save")
      return
    this_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(this_dir, cls.filename)

    # Back up (rename instead of overwrite) the old data if applicable
    if backup:
      # rename the current <filename>.json to <filename>-<timestamp>.json
      old_basename = cls.filename[:-5] # strip ".json"
      unix_time = time.strftime("%s")
      backup_name = os.path.join(this_dir, f'{old_basename}-{unix_time}.json')
      if os.path.isfile(file_path):
        os.rename(file_path, backup_name)
      else:
        debug_print("There's nothing to back up.")

    # Save data to file, if there is data
    data = cls._serialize()
    #debug_print("Dumping:", data)
    if data: # unnecessary check?
      with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)
    else:
      debug_print("There isn't enough data to write.")

  @classmethod
  def remap_ID(cls, curr_ID: str, prev_ID: str) -> None:
    """ Remap one Discord ID to another (in case they lose their account etc).
        Should be restricted to admin-only. """
    cls.ID_map[curr_ID] = prev_ID


class Player():
  # Values saved = banned: bool, ID: str, records: dict
  # self.records: map[tuple,dict] =
  #   ('NA','PC'): ("matches_total":int, "elo":float), ...
  def __init__(self, ID, records=dict(), banned=False, display_name=""):
    self.ID = ID
    self.records = records
    self.banned = banned
    self.display_name = display_name

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
      this_record = value
      this_record["region"] = region
      this_record["platform"] = platform
      serialized_records.append(this_record)

    data = {
      "display_name": self.display_name,
      "ID": self.ID,
      "records": serialized_records,
      "banned": self.banned,
    }
    debug_print("Serialized player data:", data)
    return data

  def get_summary(self) -> None:
    """ Return a string summary of this Player. """
    output = f"-# {self.display_name} has the following records:\n"
    any_found = False
    for (region,platform),record in self.records.items():
      if record['matches_total']:
        # TODO: sort
        output += (f"-# * {region}-{platform}: {int(record['elo'])} elo from {record['matches_total']} matches\n")
        any_found = True
    if not any_found:
      output += "-# * None, they're new!\n"
    if self.banned:
      output += "and they're BANNED\n"
    output = output.strip()
    return output

