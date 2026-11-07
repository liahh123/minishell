"""deadlock.py - Module 3: deadlock detection and Banker's algorithm.

Commands:  deadlock detect FILE
           deadlock banker FILE [--request PID r1 r2 ... rm]

Input file ('#' starts a comment):
    5 3                 # number of processes, number of resource types
    Allocation          # N rows of M numbers
    0 1 0
    ...
    Max                 # N rows of M numbers (needed by Banker's algorithm)
    ...
    Request             # OPTIONAL: what each process is waiting for right now.
    ...                 #   `detect` uses it; if it is missing, detect uses Need.
    Available           # 1 row of M numbers
    3 3 2

    Need = Max - Allocation

Exit codes (so && and || work):  0 = no deadlock / safe,  1 = deadlock / unsafe
(or request denied),  2 = bad input.

Written from scratch; no deadlock library is used.
"""
import sys

SECTIONS = {'allocation', 'max', 'request', 'available'}
ALIASES = {'alloc': 'allocation', 'avail': 'available', 'req': 'request'}


# --------------------------------------------------------------------------
# Reading the system description
# --------------------------------------------------------------------------
def parse_system(text):
    """Return a dict with n, m, alloc, max, request, avail, need.  ValueError if bad."""
    rows = []
    for no, line in enumerate(text.splitlines(), 1):
        line = line.split('#')[0].strip()
        if line:
            rows.append((no, line))
    if not rows:
        raise ValueError('the file is empty')
    first = rows[0][1].split()
    if len(first) != 2 or not all(x.isdigit() for x in first):
        raise ValueError(f"line {rows[0][0]}: the first line must be 'NUMBER_OF_PROCESSES NUMBER_OF_RESOURCES'")
    n, m = int(first[0]), int(first[1])
    if m < 1:
        raise ValueError('there must be at least 1 resource type')

    sections, cur = {}, None
    for no, line in rows[1:]:
        f = line.split()
        if len(f) == 1 and f[0].rstrip(':').isalpha():
            name = f[0].rstrip(':').lower()
            name = ALIASES.get(name, name)
            if name not in SECTIONS:
                raise ValueError(f"line {no}: unknown section '{f[0]}' (use Allocation, Max, Request, Available)")
            if name in sections:
                raise ValueError(f"line {no}: section '{f[0]}' appears twice")
            cur = name
            sections[cur] = []
            continue
        if cur is None:
            raise ValueError(f"line {no}: expected a section name before the numbers")
        try:
            vals = [int(x) for x in f]
        except ValueError:
            raise ValueError(f'line {no}: only whole numbers are allowed')
        if any(v < 0 for v in vals):
            raise ValueError(f'line {no}: negative numbers are not allowed')
        if len(vals) != m:
            raise ValueError(f'line {no}: expected {m} numbers, found {len(vals)}')
        sections[cur].append(vals)

    for name in ('allocation', 'available'):
        if name not in sections:
            raise ValueError(f"the '{name.capitalize()}' section is missing")
    if 'max' not in sections and 'request' not in sections:
        raise ValueError("need a 'Max' section (Banker's) or a 'Request' section (detection)")
    for name, matrix in sections.items():
        need_rows = 1 if name == 'available' else n
        if len(matrix) != need_rows:
            raise ValueError(f"'{name.capitalize()}' has {len(matrix)} row(s), expected {need_rows}")

    alloc, mx, req = sections['allocation'], sections.get('max'), sections.get('request')
    need = None
    if mx is not None:
        for i in range(n):
            for j in range(m):
                if alloc[i][j] > mx[i][j]:
                    raise ValueError(f'P{i} holds more of resource {label(j, m)} than its Max')
        need = [[mx[i][j] - alloc[i][j] for j in range(m)] for i in range(n)]
    return {'n': n, 'm': m, 'alloc': alloc, 'max': mx, 'request': req,
            'avail': sections['available'][0], 'need': need}


def label(j, m):
    return chr(65 + j) if m <= 26 else f'R{j}'


def fmt(v):
    return ' '.join(str(x) for x in v)


def fmt_tuple(v):
    return '(' + ', '.join(str(x) for x in v) + ')'


def le(a, b):
    """True if vector a <= vector b in every position."""
    return all(x <= y for x, y in zip(a, b))


# --------------------------------------------------------------------------
# Algorithms
# --------------------------------------------------------------------------
def safety(alloc, need, avail):
    """Banker's safety check.

    Pretend processes finish one by one: a process can finish when Need <= Work,
    and then returns its Allocation to Work.  Returns (is_safe, sequence, steps)
    where steps is a list of (process, work_before, work_after).
    """
    n = len(alloc)
    work, done, seq, steps = list(avail), [False] * n, [], []
    progress = True
    while progress:
        progress = False
        for i in range(n):
            if not done[i] and le(need[i], work):
                after = [w + a for w, a in zip(work, alloc[i])]
                steps.append((i, list(work), after))
                work, done[i] = after, True
                seq.append(i)
                progress = True
    return all(done), seq, steps


def detect(alloc, request, avail):
    """Deadlock detection.  Returns the list of deadlocked process numbers.

    Same loop as the safety check but uses Request instead of Need, and a
    process that holds nothing counts as finished from the start.
    """
    n = len(alloc)
    work = list(avail)
    done = [all(a == 0 for a in alloc[i]) for i in range(n)]
    progress = True
    while progress:
        progress = False
        for i in range(n):
            if not done[i] and le(request[i], work):
                work = [w + a for w, a in zip(work, alloc[i])]
                done[i] = True
                progress = True
    return [i for i in range(n) if not done[i]]


def try_request(sysd, i, req):
    """Banker's resource-request algorithm for process i.

    Returns (decision, lines) where decision is 'granted', 'denied', 'wait' or 'error'.
    The system dictionary is never changed (we work on copies).
    """
    alloc, need, avail, m = sysd['alloc'], sysd['need'], sysd['avail'], sysd['m']
    L = [f'Request: P{i} asks for {fmt_tuple(req)}']
    ok = le(req, need[i])
    L.append(f'  1. Request <= Need of P{i}?   {fmt_tuple(req)} <= {fmt_tuple(need[i])}: {"yes" if ok else "NO"}')
    if not ok:
        L.append(f'Decision: ERROR - P{i} asked for more than its declared maximum claim.')
        return 'error', L
    ok = le(req, avail)
    L.append(f'  2. Request <= Available?      {fmt_tuple(req)} <= {fmt_tuple(avail)}: {"yes" if ok else "NO"}')
    if not ok:
        L.append(f'Decision: P{i} must WAIT - the resources are not available right now.')
        return 'wait', L
    new_avail = [a - r for a, r in zip(avail, req)]
    new_alloc = [row[:] for row in alloc]
    new_need = [row[:] for row in need]
    new_alloc[i] = [a + r for a, r in zip(new_alloc[i], req)]
    new_need[i] = [a - r for a, r in zip(new_need[i], req)]
    L.append(f'  3. Pretend to grant it: Available = {fmt(new_avail)}, '
             f'Allocation P{i} = {fmt(new_alloc[i])}, Need P{i} = {fmt(new_need[i])}')
    safe, seq, _ = safety(new_alloc, new_need, new_avail)
    if safe:
        L.append(f'  4. Safety check on the new state: SAFE, sequence {" -> ".join("P%d" % s for s in seq)}')
        L.append('Decision: GRANTED')
        return 'granted', L
    L.append('  4. Safety check on the new state: UNSAFE (no process order can finish)')
    L.append('Decision: DENIED - granting it could lead to deadlock. Changes are undone; P%d must wait.' % i)
    return 'denied', L


def recovery(alloc, request, avail):
    """Bonus: terminate the deadlocked process holding the most resources, repeat."""
    alloc = [row[:] for row in alloc]
    request = [row[:] for row in request]
    work = list(avail)
    m = len(work)
    L, killed = [], []
    dead = detect(alloc, request, work)
    while dead:
        victim = max(dead, key=lambda i: (sum(alloc[i]), -i))
        L.append(f'  terminate P{victim} (holds {fmt_tuple(alloc[victim])}, {sum(alloc[victim])} units)')
        work = [w + a for w, a in zip(work, alloc[victim])]
        alloc[victim], request[victim] = [0] * m, [0] * m
        killed.append(victim)
        dead = detect(alloc, request, work)
        L.append(f'    -> Available is now {fmt_tuple(work)}; still deadlocked: '
                 + (', '.join('P%d' % d for d in dead) if dead else 'none'))
    return killed, L


# --------------------------------------------------------------------------
# Printing
# --------------------------------------------------------------------------
def format_state(s):
    n, m = s['n'], s['m']
    cols = [('Allocation', s['alloc'])]
    if s['max'] is not None:
        cols.append(('Max', s['max']))
        cols.append(('Need', s['need']))
    if s['request'] is not None:
        cols.append(('Request', s['request']))
    widths = [max([len(t)] + [len(fmt(r)) for r in rows]) for t, rows in cols]
    L = [f'Processes: {n}   Resource types: {m} ({", ".join(label(j, m) for j in range(m))})',
         f'{"":<6}' + '  '.join(f'{t:<{w}}' for (t, _), w in zip(cols, widths))]
    for i in range(n):
        L.append(f'{"P%d" % i:<6}' + '  '.join(f'{fmt(rows[i]):<{w}}' for (_, rows), w in zip(cols, widths)))
    L.append(f'Available: {fmt(s["avail"])}')
    return '\n'.join(L)


def names(idx):
    return ', '.join('P%d' % i for i in idx)


def detect_report(s):
    if s['request'] is not None:
        waiting, basis = s['request'], 'the Request matrix'
    elif s['need'] is not None:
        waiting, basis = s['need'], 'Need (Max - Allocation), because no Request matrix was given'
    else:
        raise ValueError("detection needs a 'Request' or 'Max' section")
    L = ['=== Deadlock detection ===', format_state(s), '', f'Detection uses {basis}.']
    if s['n'] == 0:
        L.append('Result: there are no processes, so there is no deadlock.')
        return '\n'.join(L) + '\n', 0
    dead = detect(s['alloc'], waiting, s['avail'])
    if not dead:
        L.append('Result: NO DEADLOCK - every process can eventually finish.')
        return '\n'.join(L) + '\n', 0
    L.append(f'Result: DEADLOCK - these processes are stuck waiting for each other: {names(dead)}')
    killed, steps = recovery(s['alloc'], waiting, s['avail'])
    L.append('')
    L.append('Recovery suggestion (process termination):')
    L += steps
    L.append(f'  Deadlock cleared after terminating: {names(killed)}.')
    first = killed[0]
    L.append(f'Alternative (preemption): take the resources held by P{first} '
             f'{fmt_tuple(s["alloc"][first])} away, give them to the other stuck processes, '
             f'then roll P{first} back and restart it.')
    return '\n'.join(L) + '\n', 1


def banker_report(s, request=None):
    if s['need'] is None:
        raise ValueError("Banker's algorithm needs a 'Max' section")
    L = ["=== Banker's algorithm ===", format_state(s), '', 'Safety check:']
    if s['n'] == 0:
        L.append('Result: SAFE (there are no processes).')
        base_safe = True
    else:
        base_safe, seq, steps = safety(s['alloc'], s['need'], s['avail'])
        for k, (i, before, after) in enumerate(steps, 1):
            L.append(f'  step {k}: P{i} can finish (Need {fmt(s["need"][i])} <= Work {fmt(before)})'
                     f' -> releases {fmt(s["alloc"][i])}, Work = {fmt(after)}')
        if base_safe:
            L.append(f'Result: SAFE   Safe sequence: {" -> ".join("P%d" % i for i in seq)}')
        else:
            stuck = [i for i in range(s['n']) if i not in seq]
            L.append(f'  no remaining process has Need <= Work, so these cannot finish: {names(stuck)}')
            L.append('Result: UNSAFE   (no safe sequence exists)')
    code = 0 if base_safe else 1
    if request is not None:
        pid, req = request
        L.append('')
        decision, lines = try_request(s, pid, req)
        L += lines
        code = 0 if decision == 'granted' else 1
    return '\n'.join(L) + '\n', code


# --------------------------------------------------------------------------
# The `deadlock` shell command
# --------------------------------------------------------------------------
USAGE = ('usage: deadlock detect FILE\n'
         '       deadlock banker FILE [--request PID r1 r2 ... rm]\n'
         '  Example: deadlock banker system.txt --request 1 1 0 2   (P1 asks for 1,0,2)\n')


def _parse_request(tokens, s):
    if len(tokens) != s['m'] + 1:
        raise ValueError(f"--request needs a process number and {s['m']} amounts (got {len(tokens)} values)")
    pid_text = tokens[0]
    if pid_text[:1] in 'Pp':
        pid_text = pid_text[1:]
    try:
        pid = int(pid_text)
        req = [int(x) for x in tokens[1:]]
    except ValueError:
        raise ValueError('--request values must be whole numbers')
    if not 0 <= pid < s['n']:
        raise ValueError(f"no such process: P{pid} (valid: P0..P{s['n'] - 1})" if s['n'] else 'there are no processes')
    if any(r < 0 for r in req):
        raise ValueError('--request amounts cannot be negative')
    return pid, req


def cmd_deadlock(args, stdin):
    if not args or args[0] not in ('detect', 'banker'):
        return '', (f"deadlock: unknown mode '{args[0]}'\n" if args else '') + USAGE, 2
    mode, rest, req_tokens, files = args[0], list(args[1:]), None, []
    if '--request' in rest:
        k = rest.index('--request')
        req_tokens, rest = rest[k + 1:], rest[:k]
        if mode == 'detect':
            return '', "deadlock: --request only works with 'banker'\n" + USAGE, 2
    for a in rest:
        if a.startswith('-') and len(a) > 1:
            return '', f"deadlock: unknown option '{a}'\n" + USAGE, 2
        files.append(a)
    if len(files) > 1:
        return '', 'deadlock: only one input file is allowed\n' + USAGE, 2
    try:
        if files:
            with open(files[0]) as fh:
                text = fh.read()
        elif stdin.strip():
            text = stdin
        else:
            return '', 'deadlock: no input. Give a FILE or pipe in a system description.\n' + USAGE, 2
        s = parse_system(text)
        if mode == 'detect':
            out, code = detect_report(s)
        else:
            request = _parse_request(req_tokens, s) if req_tokens is not None else None
            out, code = banker_report(s, request)
        return out, '', code
    except OSError as e:
        return '', f'deadlock: {files[0]}: {e.strerror or e}\n', 2
    except ValueError as e:
        return '', f'deadlock: {files[0] if files else "input"}: {e}\n', 2


if __name__ == '__main__':
    text = '' if sys.stdin.isatty() else sys.stdin.read()
    o, e, c = cmd_deadlock(sys.argv[1:], text)
    sys.stdout.write(o)
    sys.stderr.write(e)
    sys.exit(c)
