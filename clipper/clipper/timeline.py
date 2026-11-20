"""Keep-ranges for a clip (dead air removed) and source<->output time mapping."""


def speech_ranges(words, start, end, tl):
    """Merge word spans inside [start, end] into speech ranges, padded."""
    pad, max_gap = tl["pad"], tl["max_gap"]
    spans = [(max(start, w["start"] - pad), min(end, w["end"] + pad))
             for w in words if w["end"] > start and w["start"] < end]
    spans.sort()
    merged = []
    for a, b in spans:
        if merged and a - merged[-1][1] <= max_gap:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def keep_ranges(clip, words, tl):
    """Ranges of source time that survive into the clip.

    Explicit clip["segments"] win. Otherwise, with trim_silence, long silences are
    shortened to keep_gap (split evenly so both sides keep a breath)."""
    start, end = float(clip["start"]), float(clip["end"])
    if clip.get("segments"):
        # Explicit segments: clamp to the clip, sort, merge overlaps (output is chronological).
        segs = sorted([max(start, float(a)), min(end, float(b))] for a, b in clip["segments"])
        out = []
        for a, b in segs:
            if b <= a:
                continue
            if out and a <= out[-1][1]:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        if not out:
            raise ValueError(f"{clip.get('id')}: segments が start〜end の範囲に1つもありません")
        return out
    if not clip.get("trim_silence", True):
        return [[start, end]]
    sp = speech_ranges(words, start, end, tl)
    if not sp:
        return [[start, end]]
    keep, half = [], tl["keep_gap"] / 2
    for i, (a, b) in enumerate(sp):
        a2 = a - (half if i else 0)
        b2 = b + (half if i < len(sp) - 1 else 0)
        keep.append([max(start, a2), min(end, b2)])
    # Let the ending breathe: the reaction after the last word is often the payoff.
    keep[-1][1] = max(keep[-1][1], min(end, keep[-1][1] + 0.6))
    out = []
    for a, b in keep:
        if out and a <= out[-1][1] + 0.01:
            out[-1][1] = max(out[-1][1], b)
        elif b - a >= tl["min_segment"]:
            out.append([a, b])
    return out or [[start, end]]


class Mapper:
    """Maps source time to output time across the kept ranges."""

    def __init__(self, ranges):
        self.ranges = ranges
        self.offsets, acc = [], 0.0
        for a, b in ranges:
            self.offsets.append(acc)
            acc += b - a
        self.duration = acc

    def to_out(self, t):
        """Output time for source time t, or None if t falls in a removed gap."""
        for (a, b), off in zip(self.ranges, self.offsets):
            if a <= t <= b:
                return off + (t - a)
        return None

    def to_out_clamped(self, t):
        for (a, b), off in zip(self.ranges, self.offsets):
            if t < a:
                return off
            if t <= b:
                return off + (t - a)
        return self.duration

    def span(self, s, e):
        """Map a source interval to output, clipped to kept material."""
        os_, oe = self.to_out_clamped(s), self.to_out_clamped(e)
        return (os_, oe) if oe - os_ > 0.05 else None
