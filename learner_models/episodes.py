"""
Chops a session into CODE / RUN / RESET episodes and the pauses between them.

Events are walked in time order and grouped into episodes, stopping whenever there's
a hard-pause boundary, and folding the "soft" UI events into whatever episode is around
them so they don't clutter the timeline.

Each episode is a dict {episode_type, boundary, start_idx, end_idx, start_ts, end_ts,
event_count, soft_indices}. start_idx is inclusive and end_idx is exclusive. Each pause
is a dict {after_idx, duration, episode_type, boundary}.
"""
from .constants import (
    CODE_EVENTS,
    PAUSE_MAX_S,
    PAUSE_THRESHOLD_S,
    POST_RUN_PAUSE_TRANSPARENT_TYPES,
    RESET_EVENTS,
    RUN_END_EVENTS,
    RUN_START_EVENTS,
    SHORT_PAUSE_MIN_S,
    SOFT_EVENT_TYPES,
)


def _classify_event(event_type: str) -> str:
    """Map an event type to the episode kind it would open (CODE, RUN, or RESET),
    or '' if it opens nothing on its own."""
    if event_type in CODE_EVENTS:
        return 'CODE'
    if event_type in RUN_START_EVENTS:
        return 'RUN'
    if event_type in RESET_EVENTS:
        return 'RESET'
    return ''


def segment_session(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """The one to call. Three rules decide the result:

    1. A long idle gap (>= PAUSE_THRESHOLD_S) becomes an INACTIVE_PAUSE hard boundary.
    2. CODE/RUN/RESET episodes respect those boundaries and pull soft events into
       whatever episode surrounds them. RESET is a single event, RUN runs until
       projectEnd (inclusive), and CODE runs through consecutive code events.
    3. A RUN that ended cleanly on projectEnd and then sat with a gap
       (> SHORT_PAUSE_MIN_S, < PAUSE_THRESHOLD_S) before the next real event gets a
       POST_RUN_PAUSE.

    Every event needs an 'event_type' (str) and a 'ts' (float seconds, or None). An
    event with no ts still gets segmented, it just can't anchor a pause.

    Returns (episodes, pauses), pauses sorted by after_idx so a timeline can line them up
    by position.
    """
    seg = SessionSegmenter()
    for event in events:
        seg.push(event.get('event_type', ''), event.get('ts'))
    return seg.result()


class SessionSegmenter:
    """The incremental form of segment_session for a live host. Push events in
    order with push(event_type, ts). result() returns the (episodes, pauses) for
    every event pushed so far, with indices counted from the first push. Each push does a constant amount of work, so a
    host no longer re-segments its whole buffer whenever one event arrives.

    Each event goes through the three rules in turn. The gap before it decides an
    INACTIVE_PAUSE, the open CODE or RUN episode either absorbs it or closes, and
    a RUN that ended on projectEnd waits for the next non-transparent event to
    decide its POST_RUN_PAUSE.

    forget_before(index) drops finished episodes and pauses before an index, so
    a long-lived host can keep only a recent window in memory.
    """

    def __init__(self):
        self.count = 0
        self._closed = []           # finished episodes, in order
        self._open = None           # the CODE or RUN episode still absorbing events
        self._inactive = []
        self._post_run = []
        self._awaiting = []         # (last_idx, last_ts) of RUNs closed on projectEnd
        self._prev_ts = None

    def push(self, event_type, ts):
        i = self.count
        self.count += 1
        et = event_type or ''

        # Rule 1: the gap between the previous event and this one.
        hard = False
        if i >= 1 and self._prev_ts is not None and ts is not None:
            gap = ts - self._prev_ts
            if SHORT_PAUSE_MIN_S < gap <= PAUSE_MAX_S and gap >= PAUSE_THRESHOLD_S:
                self._inactive.append({
                    'after_idx': i - 1,
                    'duration': gap,
                    'episode_type': 'INACTIVE_PAUSE',
                    'boundary': 'hard',
                })
                hard = True
        self._prev_ts = ts

        # Rule 3: the first non-transparent event after a clean RUN end.
        if et not in POST_RUN_PAUSE_TRANSPARENT_TYPES and self._awaiting:
            for last_idx, last_ts in self._awaiting:
                if ts is None or last_ts is None:
                    continue
                gap = ts - last_ts
                if gap <= SHORT_PAUSE_MIN_S or gap >= PAUSE_THRESHOLD_S:
                    continue
                self._post_run.append({
                    'after_idx': last_idx,
                    'duration': gap,
                    'episode_type': 'POST_RUN_PAUSE',
                    'boundary': 'hard',
                })
            self._awaiting = []

        # Rule 2: extend or close the open episode.
        ep = self._open
        if ep is not None:
            if hard:
                self._close()
            elif ep['episode_type'] == 'RUN':
                if et in RUN_END_EVENTS:
                    self._extend(i, ts)
                    self._close()
                    self._awaiting.append((i, ts))
                    return
                if et in SOFT_EVENT_TYPES:
                    ep['soft_indices'].append(i)
                    self._extend(i, ts)
                    return
                self._close()
            else:  # CODE
                if et in CODE_EVENTS:
                    self._extend(i, ts)
                    return
                if et in SOFT_EVENT_TYPES:
                    ep['soft_indices'].append(i)
                    self._extend(i, ts)
                    return
                self._close()

        if et in SOFT_EVENT_TYPES:
            return
        kind = _classify_event(et)
        if not kind:
            return
        episode = {
            'episode_type': kind,
            'boundary': 'soft',     # only pauses are hard boundaries
            'start_idx': i,
            'end_idx': i + 1,
            'start_ts': ts,
            'end_ts': ts,
            'event_count': 1,
            'soft_indices': [],
        }
        if kind == 'RESET':
            self._closed.append(episode)
        else:
            self._open = episode

    def _extend(self, i, ts):
        ep = self._open
        ep['end_idx'] = i + 1
        ep['end_ts'] = ts
        ep['event_count'] = ep['end_idx'] - ep['start_idx']

    def _close(self):
        self._closed.append(self._open)
        self._open = None

    def result(self):
        """(episodes, pauses) for everything pushed, as segment_session returns
        them. The lists and dicts are copies the caller may keep or change."""
        episodes = [dict(ep, soft_indices=list(ep['soft_indices'])) for ep in self._closed]
        if self._open is not None:
            episodes.append(dict(self._open, soft_indices=list(self._open['soft_indices'])))
        pauses = sorted([dict(p) for p in self._inactive + self._post_run],
                        key=lambda p: p['after_idx'])
        return episodes, pauses

    def forget_before(self, index):
        """Drop finished episodes that start before index and pauses before it."""
        self._closed = [ep for ep in self._closed if ep['start_idx'] >= index]
        self._inactive = [p for p in self._inactive if p['after_idx'] >= index]
        self._post_run = [p for p in self._post_run if p['after_idx'] >= index]
