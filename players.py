""" Module defining classes relating to Players (not lobbies). """

import os
import json
import time
import asyncio # to autoclose lobbies
from copy import copy
from basic_functions import debug_print

DEFAULT_ELO = 1000.0 # only used for new Players


class PlayerManager():
  """ A singleton class to manage Players, including saving and loading. """
  filename: str = None
  players: dict[str, Player] = {}
  id_map: dict[str, str] = {} # curr -> prev; TODO: add user-facing interface
  should_save: bool = False # dirty "bit" to track changes

  @classmethod
  def initialize(cls, filename: str = 'data.json'):
    """ Initialize the class. """
    cls.filename = filename
    cls._load_data()

  @classmethod
  def _load_data(cls) -> None:
    """ Load players,id_map from a file, if it exists.
        Assume all input data is valid. """
    # Load the file if it exists
    this_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(this_dir, cls.filename)
    if not os.path.isfile(file_path):
      debug_print("No input file found.")
      # use default values for the variables
      return
    with open(file_path, "r", encoding='u8') as f:
      json_data = json.load(f)

    # Unpack the players
    for p in json_data['players']:
      debug_print('Reading player:', p)
      ID = p['ID']
      # Deserialize the records
      records = {}
      for r in p['records']:
        # Move the region and platform from values to keys
        region = r['region']
        platform = r['platform']
        del r['region'], r['platform']
        records[(region, platform)] = r
      del p['records'] # use the created `records`, not the loaded one
      cls.players[ID] = Player(**p, records=records)

    # Unpack the id_map
    for im in json_data['id_map']:
      debug_print('Reading (IDs):', im)
      ref_id = im['ref_id']
      orig_id = im['orig_id']
      debug_print(f'{ref_id} -> {orig_id}')
      cls.id_map[ref_id] = orig_id

  @classmethod
  def debug_print_players(cls) -> None:
    """ Print all players, for debugging. """
    for player in cls.players.values():
      debug_print(vars(player))

  @classmethod
  def get_player(cls, ID: str) -> Player:
    """ Fetch a player by their ID; Create them if they don't exist;
        Resolve their ID if it's mapped. Error on a circular pointer chain. """
    checked_ids = set()
    while ID in cls.id_map:
      if ID in checked_ids:
        raise RuntimeError("get_player circular pointer error")
      checked_ids.add(ID)
      ID = cls.id_map[ID]
    if ID not in cls.players:
      cls.should_save = True
      debug_print(f"Making a new player with {ID=}")
      cls.players[ID] = Player(ID)
    return cls.players[ID]

  @classmethod
  def _serialize(cls) -> dict:
    """ Create serialized representation of this object, for json. """
    epoch_time = int(time.time())
    readable_time = time.strftime("%Y-%m-%d at %H:%M:%S %Z")
    data = {
      "timestamp": [epoch_time, readable_time],
      "id_map": cls.id_map,
      "default_elo": DEFAULT_ELO,
      "players": [player.serialize() for player in cls.players.values()],
    }
    return data

  @classmethod
  def save_to_file(cls, backup=False) -> None:
    """ Save player data to a file, optionally backing up the old file.
        Note: 'Elo' is just for reference, and should be re-calculated
        during bot downtime using `recalculate_elo.py`. """
    this_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(this_dir, cls.filename)
    unix_time = int(time.time())
    old_basename = cls.filename[:-5] # strip ".json"
    new_backup_name = os.path.join(this_dir, f'{old_basename}-{unix_time}.json')
    data = cls._serialize()
    def save(msg: str = "Saving..."):
      """ Save `data` to `file_path`. Check and update `cls.should_save`. """
      if cls.should_save:
        cls.should_save = False
        debug_print(msg)
        with open(file_path, 'w', encoding='u8') as f:
          json.dump(data, f, indent=2)
      else:
        debug_print("Not saving: nothing has changed.")

    # Don't check `backup` if `file_path` not present
    if not os.path.isfile(file_path):
      save("Saving without backing up...")
      return

    # Back up (rename instead of overwrite) the old data if applicable
    if backup and cls.should_save:
      os.rename(file_path, new_backup_name)

    # Finally, do a generic save
    save()

  @classmethod
  def remap_id(cls, curr_id: str, prev_id: str) -> None:
    """ Remap one Discord ID to another (in case they lose their account etc).
        Should be restricted to admin-only. """
    if curr_id not in cls.id_map or cls.id_map[curr_id] != prev_id:
      cls.should_save = True
      cls.id_map[curr_id] = prev_id

  @classmethod
  async def autosave(cls, period: float, backup: bool) -> None:
    """ Start the autosaving process.
        Assume autosaving is enabled if this method is called. """
    while True:
      await asyncio.sleep(period)
      cls.save_to_file(backup=backup)


class Player():
  """ Manage a single player. """
  # self.records: map[tuple,dict] =
  #   { ('NA','PC'): {"matches_total":int, "elo":float}, ... }
  def __init__(self,
      ID: str,
      banned: bool = False,
      display_name: str = "",
      records: dict = None # set to None, because using a mutable default arg is problematic
    ) -> None:
    self.ID = ID
    self.banned = banned
    self.display_name = display_name
    if records:
      self.records = records
    else:
      self.records = {}

  def get_record(self, region, platform) -> dict:
    """ Fetch and return record. Create one if it doesn't exist. """
    couple = (region, platform)
    if couple not in self.records:
      self.records[couple] = {
        "matches_total": 0,
        "elo": DEFAULT_ELO
      }
    return self.records[couple]

  def get_elo(self, region, platform) -> float:
    """ Fetch a Player's elo. """
    return self.get_record(region, platform)['elo']

  def serialize(self) -> dict:
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
    return data

  def get_summary(self) -> None:
    """ Return a string summary of this Player. """
    output = f"**{self.display_name}** has the following records:\n"
    any_found = False
    for (region,platform),record in self.records.items():
      if record['matches_total']:
        output += (f"* {region}-{platform}: **{int(record['elo'])}** Elo, {record['matches_total']} matches\n")
        any_found = True
    if not any_found:
      output += "* None, they're new!\n"
    if self.banned:
      output += "...and they're **BANNED**\n"
    return output
