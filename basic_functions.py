""" Module defining functions used throughout the project. """

import time
import textwrap

CONSOLE_WIDTH = 100 # for wrapping


def debug_print(*args, **kwargs):
  """ Print to console with flush=True; Timestamp, justify, and indent string. """
  sep = kwargs.get('sep', ' ')
  end = kwargs.get('end', '\n')
  time_str = time.strftime('[%H:%M:%S] ')
  # Create semifinal string
  text = time_str + sep.join(map(str, args))
  # Split lines to preverve line breaks and join after wrapping.
  lines = text.split('\n')
  output = '\n'.join([
    # initial line(s) (pre-'\n')
    textwrap.fill(
      lines[0],
      width=CONSOLE_WIDTH,
      subsequent_indent=' ' * len(time_str)
    ),
    # subsequent lines
    *[
      textwrap.fill(
        line,
        width=CONSOLE_WIDTH,
        initial_indent=' ' * len(time_str),
        subsequent_indent=' ' * len(time_str)
      )
      for line in lines[1:]
    ]
  ]).strip()
  print(output, end=end, flush=True)


def create_elo_function(
    K: float = 25,      # The elo swing of a fair match
    diff: float = 400,  # "A player with +`diff` Elo...
    xtimes: float = 10, # ... is `xtimes` times as likely to win"
  ):
  """ Create and return a personalized Elo calculation function. """
  def elo_function(p1, p2: float, p1_wins: float) -> dict[str, float]:
    # p1_wins: 0 = loss, 1 = win, 0.5 = Draw
    p1_expected: float = 1 / (1 + xtimes ** ((p2 - p1) / diff))
    p2_expected: float = 1 / (1 + xtimes ** ((p1 - p2) / diff))
    p1_gain = K * (p1_wins - p1_expected)
    p2_gain = K * ((1 - p1_wins) - p2_expected)
    return {"p1_gain": p1_gain, "p2_gain": p2_gain}
  return elo_function


def async_cache(func):
  """ Cache the result of an async function. """
  cache = {}
  async def wrapper(arg):
    if arg in cache:
      return cache[arg]
    result = await func(arg)
    cache[arg] = result
    return result
  return wrapper
