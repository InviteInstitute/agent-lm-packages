"""
Identity-switch detection: deciding when a tracked student's identity "switched".

Two kinds of switch matter, both read off the live event stream:

  * casing -- the same handle arrives spelled differently (cobra3 -> Cobra3).
              Only surfaces once identity is treated case-insensitively, so both
              spellings map to the same student; until then this stays dormant.
  * class  -- the same handle turns up under a different classCode
              (FPFVDH -> AFURRR): the signal that one person/device is active in
              two classes.

Pure and stateless: the caller compares each event against the student's
last-seen values and records any switch however it likes. Deduping is the
caller's job (update the last-seen values after each event, so an unchanged
value never re-fires).
"""


def detect_switches(prev_id, prev_class, curr_id, curr_class):
    """Return the switches this event represents for one tracked student.

    Args, all strings (or None/"" when there's no prior value yet):
        prev_id     last-seen studentID casing   (e.g. "cobra3")
        prev_class  last-seen classCode          (e.g. "FPFVDH")
        curr_id     this event's studentID casing (e.g. "Cobra3")
        curr_class  this event's classCode        (e.g. "AFURRR")

    Returns a list of (kind, from_value, to_value) tuples, casing before class:
        ("casing", prev_id,    curr_id)     same handle ignoring case, new spelling
        ("class",  prev_class, curr_class)  the classCode changed
    Both can fire from one event. Returns [] when nothing switched; a missing
    prior value (None or "") is never a switch, so the first event for a student
    and the first class it's ever seen under both read as "no switch".
    """
    switches = []
    # Same handle ignoring case, but the spelling changed. The .lower() guard
    # keeps this honest as a standalone function.
    if prev_id and curr_id and prev_id != curr_id and prev_id.lower() == curr_id.lower():
        switches.append(("casing", prev_id, curr_id))
    if prev_class and curr_class and prev_class != curr_class:
        switches.append(("class", prev_class, curr_class))
    return switches
