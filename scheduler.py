"""scheduler.py - Module 2: CPU scheduling simulator (PCB + six algorithms).

Command:  sched ALGORITHM [--quantum N] [--trace] [FILE]
          ALGORITHM = fcfs | sjn | priority | rr | mlq | mlfq | compare

Input file (one process per line, '#' starts a comment):
    # pid arrival burst priority
    P1 0 8 2
Priority is optional (default 0).  CONVENTION: LOWER NUMBER = HIGHER PRIORITY.

Every algorithm returns a *timeline*: a list of (pid, start, end) blocks and
fills in `completion` on each PCB.  One shared function then prints the PCB
table, Gantt chart, per-process table and averages, so that code is written once.

    Turnaround = Completion - Arrival
    Waiting    = Turnaround - Burst

All algorithms are written from scratch (no scheduling library is used).
"""
import copy
import sys
from collections import deque
from dataclasses import dataclass


# --------------------------------------------------------------------------
# PCB (Process Control Block) and input
# --------------------------------------------------------------------------
@dataclass
class PCB:
    pid: str
    arrival: int
    burst: int
    priority: int = 0
    remaining: int = 0
    state: str = 'New'          # New, Ready, Running, Waiting, Terminated
    completion: int = 0

    def __post_init__(self):
        self.remaining = self.burst


def parse_processes(text):
    """Turn the text of a process file into a list of PCBs (ValueError if bad)."""
    procs, seen = [], set()
    for no, line in enumerate(text.splitlines(), 1):
        line = line.split('#')[0].strip()
        if not line:
            continue
        f = line.split()
        if f[0].lower() == 'pid':                       # optional header line
            continue
        if len(f) not in (3, 4):
            raise ValueError(f"line {no}: expected 'PID ARRIVAL BURST [PRIORITY]', got '{line}'")
        try:
            arrival, burst = int(f[1]), int(f[2])
            priority = int(f[3]) if len(f) == 4 else 0
        except ValueError:
            raise ValueError(f'line {no}: arrival, burst and priority must be whole numbers')
        if arrival < 0:
            raise ValueError(f'line {no}: arrival time cannot be negative')
        if burst <= 0:
            raise ValueError(f'line {no}: burst time must be at least 1')
        if f[0] in seen:
            raise ValueError(f"line {no}: duplicate PID '{f[0]}'")
        seen.add(f[0])
        procs.append(PCB(f[0], arrival, burst, priority))
    return procs


def load(path):
    with open(path) as fh:
        return parse_processes(fh.read())


# --------------------------------------------------------------------------
# The six algorithms.  Each takes (procs, quantum) and returns a timeline.
# --------------------------------------------------------------------------
def _finish(p, t):
    p.completion, p.remaining, p.state = t, 0, 'Terminated'


def fcfs(procs, quantum=None):
    """First Come First Served: sort by arrival, run each to completion."""
    t, tl = 0, []
    for p in sorted(procs, key=lambda p: p.arrival):      # sort is stable
        t = max(t, p.arrival)                             # idle gap: jump ahead
        tl.append((p.pid, t, t + p.burst))
        t += p.burst
        _finish(p, t)
    return tl


def _pick_next(procs, key):
    """Non-preemptive: among arrived processes run the one with the smallest key."""
    t, tl, pending = 0, [], list(procs)
    while pending:
        ready = [p for p in pending if p.arrival <= t]
        if not ready:                                     # CPU idle
            t = min(p.arrival for p in pending)
            continue
        p = min(ready, key=key)
        tl.append((p.pid, t, t + p.burst))
        t += p.burst
        _finish(p, t)
        pending.remove(p)
    return tl


def sjn(procs, quantum=None):
    """Shortest Job Next (non-preemptive): smallest burst first."""
    return _pick_next(procs, lambda p: (p.burst, p.arrival))


def priority(procs, quantum=None):
    """Priority (non-preemptive): lowest number = highest priority."""
    return _pick_next(procs, lambda p: (p.priority, p.arrival))


def rr(procs, quantum=None):
    """Round-Robin: each process runs at most `quantum`, then goes to the back."""
    quantum = quantum or 4
    t, tl, q = 0, [], deque()
    pending = sorted(procs, key=lambda p: p.arrival)

    def admit():
        while pending and pending[0].arrival <= t:
            q.append(pending.pop(0))

    admit()
    while q or pending:
        if not q:                                         # CPU idle
            t = pending[0].arrival
            admit()
            continue
        p = q.popleft()
        run = min(quantum, p.remaining)
        tl.append((p.pid, t, t + run))
        t += run
        p.remaining -= run
        admit()                      # new arrivals queue BEFORE the preempted process
        if p.remaining > 0:
            q.append(p)
        else:
            _finish(p, t)
    return tl


def mlq(procs, quantum=None, boundary=2):
    """Multilevel Queue (processes never change queue).

    Queue 1 (priority <= 2, "system"): Round-Robin, quantum 4 (or --quantum).
    Queue 2 (priority  > 2, "user")  : FCFS.
    Queue 1 always has absolute priority; a Queue 2 process is paused when a
    Queue 1 process arrives and resumes (at the head of Queue 2) afterwards.
    """
    quantum = quantum or 4
    q1, q2, tl = deque(), deque(), []
    pending = sorted(procs, key=lambda p: p.arrival)
    t = 0

    def admit():
        while pending and pending[0].arrival <= t:
            p = pending.pop(0)
            (q1 if p.priority <= boundary else q2).append(p)

    while pending or q1 or q2:
        admit()
        if q1:
            p = q1.popleft()
            run = min(quantum, p.remaining)
            tl.append((p.pid, t, t + run))
            t += run
            p.remaining -= run
            admit()
            if p.remaining > 0:
                q1.append(p)
            else:
                _finish(p, t)
        elif q2:
            p = q2[0]                                     # FCFS: head of queue
            run = p.remaining
            nxt = min((x.arrival for x in pending if x.priority <= boundary), default=None)
            if nxt is not None:                           # a Queue 1 arrival preempts
                run = min(run, nxt - t)
            tl.append((p.pid, t, t + run))
            t += run
            p.remaining -= run
            if p.remaining == 0:
                q2.popleft()
                _finish(p, t)
        else:                                             # CPU idle
            t = pending[0].arrival
    return tl


def mlfq(procs, quantum=None):
    """Multilevel Feedback Queue.

    Q0: Round-Robin, quantum q (default 2)   <- every process starts here
    Q1: Round-Robin, quantum 2q (default 4)
    Q2: FCFS (runs until done)
    A process that uses its whole quantum without finishing is demoted one level.
    The CPU always serves the highest non-empty queue.  A new arrival (it enters
    Q0) preempts a process running in Q1/Q2; the preempted process is NOT demoted
    and stays at the head of its own queue.
    """
    q0 = quantum or 2
    quanta = [q0, 2 * q0, None]
    queues = [deque(), deque(), deque()]
    pending = sorted(procs, key=lambda p: p.arrival)
    t, tl = 0, []

    def admit():
        while pending and pending[0].arrival <= t:
            queues[0].append(pending.pop(0))

    while pending or any(queues):
        admit()
        lvl = next((i for i, qu in enumerate(queues) if qu), None)
        if lvl is None:                                   # CPU idle
            t = pending[0].arrival
            continue
        p = queues[lvl].popleft()
        run = p.remaining if quanta[lvl] is None else min(quanta[lvl], p.remaining)
        preempted = False
        if lvl > 0 and pending and pending[0].arrival - t < run:
            run = pending[0].arrival - t
            preempted = True
        tl.append((p.pid, t, t + run))
        t += run
        p.remaining -= run
        admit()
        if p.remaining == 0:
            _finish(p, t)
        elif preempted:
            queues[lvl].appendleft(p)
        else:
            queues[min(lvl + 1, 2)].append(p)
    return tl


ALGOS = {
    'fcfs': ('FCFS', fcfs),
    'sjn': ('SJN', sjn),
    'priority': ('Priority', priority),
    'rr': ('Round-Robin', rr),
    'mlq': ('MLQ', mlq),
    'mlfq': ('MLFQ', mlfq),
}
DEFAULT_QUANTUM = {'rr': 4, 'mlq': 4, 'mlfq': 2}


# --------------------------------------------------------------------------
# Running an algorithm and collecting statistics
# --------------------------------------------------------------------------
def merge(tl):
    """Join back-to-back blocks of the same process (nicer Gantt chart)."""
    out = []
    for pid, s, e in tl:
        if out and out[-1][0] == pid and out[-1][2] == s:
            out[-1] = (pid, out[-1][1], e)
        else:
            out.append((pid, s, e))
    return out


def simulate(key, procs, quantum=None):
    """Run one algorithm on a fresh copy of `procs` (so runs never interfere)."""
    name, fn = ALGOS[key]
    work = copy.deepcopy(procs)
    timeline = merge(fn(work, quantum))
    used_q = quantum or DEFAULT_QUANTUM.get(key)
    label = f'{name} (q={used_q})' if key in DEFAULT_QUANTUM else name
    n = len(work)
    turn = {p.pid: p.completion - p.arrival for p in work}
    wait = {p.pid: turn[p.pid] - p.burst for p in work}
    makespan = timeline[-1][2] if timeline else 0
    busy = sum(e - s for _, s, e in timeline)
    return {
        'key': key, 'name': name, 'label': label, 'procs': work, 'timeline': timeline,
        'turnaround': turn, 'waiting': wait,
        'avg_wait': sum(wait.values()) / n if n else 0.0,
        'avg_turn': sum(turn.values()) / n if n else 0.0,
        'max_wait': max(wait.values()) if n else 0,
        'switches': max(len(timeline) - 1, 0),
        'makespan': makespan,
        'utilization': 100.0 * busy / makespan if makespan else 0.0,
    }


def compare(procs, quantum=None):
    """Run all six algorithms on the same processes; return the six results."""
    return [simulate(k, procs, quantum) for k in ALGOS]


# --------------------------------------------------------------------------
# PCB states: derived from the timeline so every algorithm gets them for free
# --------------------------------------------------------------------------
def build_events(procs, tl):
    """List of (time, order, pid, old_state, new_state), sorted by time."""
    ev = []
    for p in procs:
        ev.append((p.arrival, 1, p.pid, 'New', 'Ready'))
        mine = [b for b in tl if b[0] == p.pid]
        for k, (_, s, e) in enumerate(mine):
            ev.append((s, 2, p.pid, 'Ready', 'Running'))
            last = (k == len(mine) - 1)
            ev.append((e, 0, p.pid, 'Running', 'Terminated' if last else 'Ready'))
    ev.sort(key=lambda x: (x[0], x[1]))
    return ev


def snapshot(procs, tl, t):
    """PCB rows (pid, arrival, burst, priority, remaining, state) at time t."""
    state = {p.pid: 'New' for p in procs}
    if t >= 0:
        for time_, _, pid, _, new in build_events(procs, tl):
            if time_ <= t:
                state[pid] = new
    rows = []
    for p in procs:
        done = sum(max(0, min(e, t) - s) for pid, s, e in tl if pid == p.pid) if t >= 0 else 0
        rows.append((p.pid, p.arrival, p.burst, p.priority, p.burst - done, state[p.pid]))
    return rows


def pcb_table(rows, title):
    lines = [title,
             f'{"PID":<6}{"Arrival":<9}{"Burst":<7}{"Priority":<10}{"Remaining":<11}State']
    for pid, a, b, pr, rem, st in rows:
        lines.append(f'{pid:<6}{a:<9}{b:<7}{pr:<10}{rem:<11}{st}')
    return '\n'.join(lines)


# --------------------------------------------------------------------------
# Printing
# --------------------------------------------------------------------------
def gantt_blocks(tl):
    """Timeline + explicit 'idle' blocks wherever the CPU waited."""
    blocks, clock = [], 0
    for pid, s, e in tl:
        if s > clock:
            blocks.append(('idle', clock, s))
        blocks.append((pid, s, e))
        clock = e
    return blocks


def render_gantt(blocks, width=76):
    """Text Gantt chart; wraps onto several rows if it is wide."""
    rows, cur, used = [], [], 1
    for b in blocks:
        w = max(len(b[0]) + 2, 5)
        if cur and used + w + 1 > width:
            rows.append(cur)
            cur, used = [], 1
        cur.append((b, w))
        used += w + 1
    if cur:
        rows.append(cur)
    out = []
    for row in rows:
        bar, times, pos = '|', '', 0
        for (label, s, e), w in row:
            times = times.ljust(pos) + str(s)
            bar += label.center(w) + '|'
            pos += w + 1
        times = times.ljust(pos) + str(row[-1][0][2])
        out += [bar, times, '']
    return '\n'.join(out).rstrip()


def format_report(res, trace=False):
    procs, tl = res['procs'], res['timeline']
    L = [f"=== {res['label']} ==="]
    L.append(pcb_table(snapshot(procs, tl, -1), 'PCB table (before the run):'))
    L.append('')
    if trace:
        L.append('State transitions:')
        for t, _, pid, old, new in build_events(procs, tl):
            L.append(f'  t={t:<4} {pid:<6} {old} -> {new}')
        L.append('')
    L.append('Gantt chart:')
    L.append(render_gantt(gantt_blocks(tl)))
    L.append('')
    L.append(f'{"PID":<6}{"Arrival":<9}{"Burst":<7}{"Priority":<10}{"Complete":<10}{"Turnaround":<12}Waiting')
    for p in procs:
        L.append(f'{p.pid:<6}{p.arrival:<9}{p.burst:<7}{p.priority:<10}{p.completion:<10}'
                 f'{res["turnaround"][p.pid]:<12}{res["waiting"][p.pid]}')
    L.append('')
    L.append(f'Average waiting time    : {res["avg_wait"]:.2f}')
    L.append(f'Average turnaround time : {res["avg_turn"]:.2f}')
    L.append(f'Context switches: {res["switches"]}   CPU utilization: {res["utilization"]:.1f}%')
    L.append('')
    L.append(pcb_table(snapshot(procs, tl, res['makespan']), 'PCB table (after the run):'))
    return '\n'.join(L) + '\n'


def format_comparison(results):
    L = ['=== Comparison of all six algorithms ===',
         f'{"Algorithm":<20}{"Avg Waiting":<14}{"Avg Turnaround":<17}{"Max Waiting":<13}Ctx Switches']
    for r in results:
        L.append(f'{r["label"]:<20}{r["avg_wait"]:<14.2f}{r["avg_turn"]:<17.2f}'
                 f'{r["max_wait"]:<13}{r["switches"]}')
    L.append('')
    L.append('Average waiting time (each # is about 1 time unit, scaled to fit):')
    top = max((r['avg_wait'] for r in results), default=0) or 1
    for r in results:
        L.append(f'{r["label"]:<20}{"#" * round(r["avg_wait"] / top * 40):<41}{r["avg_wait"]:.2f}')
    L.append('')
    for field, text in (('avg_wait', 'Lowest average waiting time'),
                        ('avg_turn', 'Lowest average turnaround time')):
        best = min(round(r[field], 2) for r in results)
        names = ', '.join(r['label'] for r in results if round(r[field], 2) == best)
        L.append(f'{text}: {names} ({best:.2f})')
    worst = max(r['max_wait'] for r in results)
    names = ', '.join(r['label'] for r in results if r['max_wait'] == worst)
    L.append(f'Longest single wait: {names} ({worst}), i.e. the least fair to one process')
    return '\n'.join(L) + '\n'


# --------------------------------------------------------------------------
# The `sched` shell command
# --------------------------------------------------------------------------
USAGE = ('usage: sched ALGORITHM [--quantum N] [--trace] [FILE]\n'
         '  ALGORITHM: fcfs | sjn | priority | rr | mlq | mlfq | compare\n'
         '  With no FILE, the process list is read from stdin (cat p.txt | sched fcfs).\n')


def cmd_sched(args, stdin):
    algo, quantum, trace, files, i = None, None, False, [], 0
    while i < len(args):
        a = args[i]
        if a in ('--quantum', '-q') or a.startswith('--quantum='):
            if '=' in a:
                val, i = a.split('=', 1)[1], i + 1
            elif i + 1 < len(args):
                val, i = args[i + 1], i + 2
            else:
                return '', 'sched: --quantum needs a number\n' + USAGE, 1
            try:
                quantum = int(val)
                if quantum < 1:
                    raise ValueError
            except ValueError:
                return '', f"sched: bad quantum '{val}' (must be a whole number >= 1)\n", 1
        elif a == '--trace':
            trace, i = True, i + 1
        elif a.startswith('-') and len(a) > 1:
            return '', f"sched: unknown option '{a}'\n" + USAGE, 1
        elif algo is None:
            algo, i = a.lower(), i + 1
        else:
            files.append(a)
            i += 1
    if algo is None:
        return '', USAGE, 1
    if algo == 'all':
        algo = 'compare'
    if algo != 'compare' and algo not in ALGOS:
        return '', f"sched: unknown algorithm '{algo}'\n" + USAGE, 1
    if len(files) > 1:
        return '', 'sched: only one input file is allowed\n' + USAGE, 1

    try:
        if files:
            with open(files[0]) as fh:
                procs = parse_processes(fh.read())
        elif stdin.strip():
            procs = parse_processes(stdin)
        else:
            return '', 'sched: no input. Give a FILE or pipe in a process list.\n' + USAGE, 1
    except OSError as e:
        return '', f'sched: {files[0]}: {e.strerror or e}\n', 1
    except ValueError as e:
        return '', f'sched: {files[0] if files else "input"}: {e}\n', 1

    if not procs:
        return 'No processes to schedule (the queue is empty).\n', '', 0
    if algo == 'compare':
        results = compare(procs, quantum)
        out = format_comparison(results)
        if trace:
            out += '\n' + '\n'.join(format_report(r, True) for r in results)
        return out, '', 0
    return format_report(simulate(algo, procs, quantum), trace), '', 0


if __name__ == '__main__':
    text = '' if sys.stdin.isatty() else sys.stdin.read()
    o, e, c = cmd_sched(sys.argv[1:], text)
    sys.stdout.write(o)
    sys.stderr.write(e)
    sys.exit(c)
