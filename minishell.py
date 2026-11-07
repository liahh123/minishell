#!/usr/bin/env python3
"""minishell.py - MiniShell main loop, parser, redirection, pipes, variables.

Run:   python3 minishell.py              interactive prompt
       python3 minishell.py script.txt   run the lines of a file
       python3 minishell.py -c "ls | grep py"

How a line is processed:
    text --tokenize--> words and operators
         --split on ; && ||--> pipelines (left to right, bash rules)
         --split on |--> commands
         --pull out > >> < 2> 2>> 2>&1--> words + redirections
         --expand $VARS--> run built-in --> (stdout, stderr, exit code)

Simplification (mentioned in the report): pipe data is passed between commands
as text in memory, not through real operating-system pipes.
"""
import os
import re
import sys

from builtins_cmds import BUILTINS, variables
from deadlock import cmd_deadlock
from grep_cmd import cmd_grep
from scheduler import cmd_sched

BUILTINS.update({'grep': cmd_grep, 'sched': cmd_sched, 'deadlock': cmd_deadlock})

SENT = '\x01'                     # stands for a '$' that must NOT be expanded
ASSIGN = re.compile(r'[A-Za-z_]\w*=.*', re.S)
last_status = [0]                 # value of $?


class ShellError(Exception):
    """A mistake in what the user typed (bad syntax, etc.)."""


class ExitShell(Exception):
    def __init__(self, code=0):
        super().__init__(code)
        self.code = code


# --------------------------------------------------------------------------
# Output helpers (flush stdout before stderr so messages stay in order)
# --------------------------------------------------------------------------
def emit_out(text):
    sys.stdout.write(text)
    sys.stdout.flush()


def emit_err(text):
    sys.stdout.flush()
    sys.stderr.write(text)
    sys.stderr.flush()


# --------------------------------------------------------------------------
# Tokenizer
# --------------------------------------------------------------------------
def tokenize(line):
    """Return a list of ('word', text) and ('op', symbol) tokens.

    Handles 'single quotes' (nothing expands), "double quotes" ($VAR expands),
    backslash escapes, # comments and the operators  ; && || | < > >> 2> 2>> 2>&1
    """
    toks, buf, has, i, n = [], [], False, 0, len(line)

    def flush():
        nonlocal buf, has
        if has:
            toks.append(('word', ''.join(buf)))
        buf, has = [], False

    while i < n:
        c = line[i]
        if c in ' \t':
            flush()
            i += 1
        elif c == '#' and not has:
            break
        elif c == "'":
            j = line.find("'", i + 1)
            if j < 0:
                raise ShellError("unterminated single quote (')")
            buf.append(line[i + 1:j].replace('$', SENT))
            has, i = True, j + 1
        elif c == '"':
            j, seg = i + 1, []
            while j < n and line[j] != '"':
                if line[j] == '\\' and j + 1 < n and line[j + 1] in '"\\$':
                    seg.append(SENT if line[j + 1] == '$' else line[j + 1])
                    j += 2
                else:
                    seg.append(line[j])
                    j += 1
            if j >= n:
                raise ShellError('unterminated double quote (")')
            buf.append(''.join(seg))
            has, i = True, j + 1
        elif c == '\\':
            if i + 1 < n:
                ch = line[i + 1]
                buf.append(SENT if ch == '$' else ch)
                has = True
                i += 2
            else:
                i += 1
        elif c == '2' and not has and line.startswith('2>', i):
            flush()
            for op in ('2>&1', '2>>', '2>'):
                if line.startswith(op, i):
                    toks.append(('op', op))
                    i += len(op)
                    break
        elif c in ';|&<>':
            flush()
            if c == '&':
                if line.startswith('&&', i):
                    toks.append(('op', '&&'))
                    i += 2
                else:
                    raise ShellError("background jobs ('&') are not supported")
            elif c == '|':
                two = line.startswith('||', i)
                toks.append(('op', '||' if two else '|'))
                i += 2 if two else 1
            elif c == '>':
                two = line.startswith('>>', i)
                toks.append(('op', '>>' if two else '>'))
                i += 2 if two else 1
            else:                                   # ';' or '<'
                toks.append(('op', c))
                i += 1
        else:
            buf.append(c)
            has = True
            i += 1
    flush()
    return toks


def expand(word):
    """Replace $NAME, ${NAME} and $? ; a leading ~ becomes the home directory."""
    def rep(m):
        name = m.group(1) or m.group(2)
        if name == '?':
            return str(last_status[0])
        return variables.get(name, os.environ.get(name, ''))

    word = re.sub(r'\$(?:\{(\w+)\}|(\w+|\?))', rep, word)
    if word == '~' or word.startswith('~/'):
        word = os.path.expanduser('~') + word[1:]
    return word.replace(SENT, '$')


# --------------------------------------------------------------------------
# Running commands
# --------------------------------------------------------------------------
def parse_redirects(seg):
    """Split one command's tokens into plain words and a redirection dict."""
    words, r, i = [], {}, 0
    while i < len(seg):
        kind, val = seg[i]
        if kind == 'word':
            words.append(val)
            i += 1
        elif val == '2>&1':
            r['err_to_out'] = True
            i += 1
        else:                                       # < > >> 2> 2>>
            if i + 1 >= len(seg) or seg[i + 1][0] != 'word':
                raise ShellError(f"syntax error: expected a file name after '{val}'")
            path = seg[i + 1][1]
            if val == '<':
                r['in'] = path
            elif val == '>':
                r['out'] = (path, 'w')
            elif val == '>>':
                r['out'] = (path, 'a')
            elif val == '2>':
                r['err'] = (path, 'w')
            elif val == '2>>':
                r['err'] = (path, 'a')
            else:
                raise ShellError(f"syntax error near unexpected token '{val}'")
            i += 2
    return words, r


def run_command(raw_words, redir, stdin):
    """Run ONE command. Returns (stdout_text, stderr_text, exit_code)."""
    # NAME=value assignments (a command made only of assignments sets variables)
    k = 0
    while k < len(raw_words) and ASSIGN.fullmatch(raw_words[k]):
        name, value = expand(raw_words[k]).split('=', 1)
        variables[name] = value
        k += 1
    raw_words = raw_words[k:]
    if not raw_words:
        return '', '', 0
    words = [expand(w) for w in raw_words]

    if 'in' in redir:                               # <
        path = expand(redir['in'])
        try:
            with open(path, errors='replace') as fh:
                stdin = fh.read()
        except OSError as e:
            return '', f'minishell: {path}: {e.strerror or e}\n', 1

    name = words[0]
    if name == 'exit':
        try:
            raise ExitShell(int(words[1]) if len(words) > 1 else last_status[0])
        except ValueError:
            return '', 'exit: numeric argument required\n', 2
    fn = BUILTINS.get(name)
    if fn is None:
        out, err, code = '', f'minishell: {name}: command not found\n', 127
    else:
        try:
            out, err, code = fn(words[1:], stdin)
        except Exception as e:                      # a bug in a command must not kill the shell
            out, err, code = '', f'minishell: {name}: {type(e).__name__}: {e}\n', 1

    if redir.get('err_to_out'):                     # 2>&1
        out, err = out + err, ''
    for key in ('out', 'err'):                      # > >> 2> 2>>
        if key in redir:
            path, mode = redir[key]
            path = expand(path)
            try:
                with open(path, mode) as fh:
                    fh.write(out if key == 'out' else err)
            except OSError as e:
                err += f'minishell: {path}: {e.strerror or e}\n'
                code = 1
            else:
                if key == 'out':
                    out = ''
                else:
                    err = ''
    return out, err, code


def run_pipeline(tokens):
    """cmd1 | cmd2 | cmd3 : the stdout text of one command is the stdin of the next."""
    segs = [[]]
    for t in tokens:
        if t == ('op', '|'):
            segs.append([])
        else:
            segs[-1].append(t)
    if any(not s for s in segs):
        raise ShellError("syntax error near unexpected token '|'")
    data, code = '', 0
    for seg in segs:
        words, redir = parse_redirects(seg)
        out, err, code = run_command(words, redir, data)
        if err:
            emit_err(err)
        data = out
    if data:
        emit_out(data)
    return code


def run_tokens(tokens):
    """Run  a ; b && c || d  from left to right (bash rules)."""
    if tokens and tokens[0] == ('word', 'if'):
        return run_if(tokens)
    parts, ops, cur = [], [], []
    for t in tokens:
        if t[0] == 'op' and t[1] in (';', '&&', '||'):
            parts.append(cur)
            ops.append(t[1])
            cur = []
        else:
            cur.append(t)
    parts.append(cur)
    for k, part in enumerate(parts):
        if not part and len(parts) > 1:
            trailing_semicolon = (k == len(parts) - 1 and ops[k - 1] == ';')
            if not trailing_semicolon:
                raise ShellError(f"syntax error near unexpected token '{ops[k] if k < len(ops) else ops[k - 1]}'")
    code = None
    for k, part in enumerate(parts):
        if not part:
            continue
        op = ops[k - 1] if k > 0 else None
        if k == 0 or op == ';' or (op == '&&' and code == 0) or (op == '||' and code != 0):
            code = run_pipeline(part)
            last_status[0] = code
    return 0 if code is None else code


def _join(segments):
    toks = []
    for k, seg in enumerate(segments):
        if k:
            toks.append(('op', ';'))
        toks += seg
    return toks


def run_if(tokens):
    """Bonus: if CMD; then CMD; else CMD; fi   (one line, no nesting)."""
    segs = [[]]
    for t in tokens:
        if t == ('op', ';'):
            segs.append([])
        else:
            segs[-1].append(t)
    state, cond, then, els, rest = None, [], [], [], []
    for seg in segs:
        if state == 'done':
            if seg:
                rest.append(seg)
            continue
        kw = seg[0][1] if seg and seg[0][0] == 'word' and seg[0][1] in ('if', 'then', 'else', 'fi') else None
        if kw == 'if' and state is None:
            state, seg = 'cond', seg[1:]
        elif kw == 'then' and state == 'cond':
            state, seg = 'then', seg[1:]
        elif kw == 'else' and state == 'then':
            state, seg = 'else', seg[1:]
        elif kw == 'fi' and state in ('then', 'else'):
            if len(seg) > 1:
                raise ShellError("syntax error near 'fi'")
            state = 'done'
            continue
        elif kw is not None:
            raise ShellError(f"syntax error near unexpected token '{kw}' (nested if is not supported)")
        if seg:
            {'cond': cond, 'then': then, 'else': els}[state].append(seg)
    if state != 'done':
        raise ShellError("syntax error: expected 'if CMD; then CMD; [else CMD;] fi'")
    if not cond or not then:
        raise ShellError("syntax error: 'if' needs a condition and a 'then' part")
    cond_code = run_tokens(_join(cond))
    last_status[0] = cond_code
    body = then if cond_code == 0 else els
    code = run_tokens(_join(body)) if body else 0
    if rest:
        code = run_tokens(_join(rest))
    return code


def run_line(line):
    code = run_tokens(tokenize(line))
    last_status[0] = code
    return code


def safe_run(line):
    """Run a line; report mistakes instead of crashing. Only `exit` escapes."""
    try:
        return run_line(line)
    except ExitShell:
        raise
    except ShellError as e:
        emit_err(f'minishell: {e}\n')
        last_status[0] = 2
    except Exception as e:                          # the shell must NEVER crash
        emit_err(f'minishell: error: {type(e).__name__}: {e}\n')
        last_status[0] = 1
    return last_status[0]


def run_lines(lines):
    try:
        for line in lines:
            if line.strip():
                safe_run(line.strip())
    except ExitShell as e:
        return e.code
    return last_status[0]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['-c']:
        if len(argv) < 2:
            print('usage: minishell.py [-c "command" | script_file]', file=sys.stderr)
            return 2
        return run_lines(argv[1].split('\n'))
    if argv:
        try:
            with open(argv[0]) as fh:
                return run_lines(fh.read().splitlines())
        except OSError as e:
            print(f'minishell: {argv[0]}: {e.strerror or e}', file=sys.stderr)
            return 1
    prompt = 'minishell> ' if sys.stdin.isatty() else ''
    if prompt:
        print("MiniShell - type 'help' for commands, 'exit' to quit.")
    while True:
        try:
            line = input(prompt).strip()
        except EOFError:
            if prompt:
                print()
            return last_status[0]
        except KeyboardInterrupt:
            print()
            continue
        if not line:
            continue
        try:
            safe_run(line)
        except ExitShell as e:
            return e.code
        except KeyboardInterrupt:
            print()


if __name__ == '__main__':
    sys.exit(main())
