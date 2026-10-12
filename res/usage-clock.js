/* Monotonic time only: a suspended tab never accrues the missing interval. */
class UsageClock {
  constructor(serverNow, now, idleMs = 120000) {
    this.origin = serverNow - now;
    this.last = now;
    this.activity = -Infinity;
    this.visible = false;
    this.mode = 'work';
    this.idleMs = idleMs;
    this.pending = [];
  }
  step(now, visible, mode, activity = false) {
    const gap = now - this.last;
    if (gap > 10000 || gap < 0) this.activity = -Infinity;
    else if (this.visible && gap > 0) {
      const end = Math.min(now, this.activity + this.idleMs);
      if (end > this.last) this.append(this.last, end, this.mode);
    }
    this.last = now;
    this.visible = visible;
    this.mode = mode;
    if (activity && visible) this.activity = now;
  }
  append(start, end, mode) {
    start = Math.round(start + this.origin); end = Math.round(end + this.origin);
    if (end <= start) return;
    const previous = this.pending.at(-1);
    if (previous && previous.mode === mode && previous.end_ms === start && end-previous.start_ms <= 30000) previous.end_ms = end;
    else this.pending.push({ id: crypto.randomUUID(), start_ms: start, end_ms: end, mode });
  }
  take(now) {
    const cutoff = Math.round(now + this.origin) - 110000;
    this.pending = this.pending.filter(p => p.start_ms >= cutoff);
    return this.pending.splice(0, 8);
  }
}
if (typeof module !== 'undefined') module.exports = UsageClock;
