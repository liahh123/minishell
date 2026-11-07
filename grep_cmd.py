"""grep_cmd.py - grep-like text search for MiniShell.

    grep [-i] [-v] [-n] [-o] [-c] [-F] [-E] PATTERN [FILE...]

Basic use: print every line that contains PATTERN.  The pattern is a regular
expression (Python's `re` library, which the project allows), so the bonus
features work too:  .  [a-z]  *  +  ?  \\escaping  and (capturing) groups.
Use -F to treat the pattern as plain text instead (-E is accepted and ignored).

With no FILE the command reads stdin, so `ls | grep txt` works.
Exit code: 0 = something matched, 1 = no match, 2 = error.
"""
import re

USAGE = 'usage: grep [-ivnocFE] PATTERN [FILE...]\n'


def cmd_grep(args, stdin):
    flags, i = set(), 0
    while i < len(args) and args[i].startswith('-') and len(args[i]) > 1:
        if args[i] == '--':
            i += 1
            break
        flags.update(args[i][1:])
        i += 1
    bad = flags - set('ivnocFE')
    if bad:
        return '', f"grep: invalid option -- '{sorted(bad)[0]}'\n" + USAGE, 2
    rest = args[i:]
    if not rest:
        return '', USAGE, 2
    pattern, files = rest[0], rest[1:]

    try:
        regex = re.compile(re.escape(pattern) if 'F' in flags else pattern,
                           re.I if 'i' in flags else 0)
    except re.error as e:
        return '', f'grep: invalid pattern {pattern!r}: {e}\n', 2

    out, err, matched, failed = '', '', False, False
    sources = []                              # (label, text)
    if not files:
        sources.append((None, stdin))
    for f in files:
        if f == '-':
            sources.append((None, stdin))
            continue
        try:
            with open(f, errors='replace') as fh:
                sources.append((f, fh.read()))
        except OSError as e:
            err += f'grep: {f}: {e.strerror or e}\n'
            failed = True
    show_name = len(files) > 1

    for label, text in sources:
        count = 0
        for n, line in enumerate(text.splitlines(), 1):
            found = regex.search(line) is not None
            if found == ('v' in flags):       # -v inverts the test
                continue
            count += 1
            matched = True
            if 'c' in flags:
                continue
            prefix = (f'{label}:' if show_name and label else '') + (f'{n}:' if 'n' in flags else '')
            if 'o' in flags and 'v' not in flags:
                for m in regex.finditer(line):
                    if m.group(0):
                        out += prefix + m.group(0) + '\n'
            else:
                out += prefix + line + '\n'
        if 'c' in flags:
            out += (f'{label}:' if show_name and label else '') + f'{count}\n'

    code = 2 if failed else (0 if matched else 1)
    return out, err, code
