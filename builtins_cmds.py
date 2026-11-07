"""builtins_cmds.py - Built-in commands for MiniShell (Module 1).

Every command has the same shape:

    cmd_xxx(args, stdin_text) -> (stdout_text, stderr_text, exit_code)

Exit code 0 means success. Because every command looks the same, the shell
can connect them with pipes (stdout of one becomes stdin of the next) and
redirect their output to files without special cases.

Shell variables live in the `variables` dictionary (shared with minishell.py).
"""
import os
import re
import shutil
import stat
import time

variables = {}          # NAME -> value, filled by NAME=value and read by $NAME


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _msg(e):
    """Readable text for an OSError (some errors have no strerror)."""
    return e.strerror or str(e)


def _split_opts(args):
    """Split ['-la', 'x', '-r'] into ({'l','a','r'}, ['x']).  '--' ends options."""
    flags, rest = set(), []
    for i, a in enumerate(args):
        if a == '--':
            rest.extend(args[i + 1:])
            break
        if a.startswith('-') and len(a) > 1 and not a[1:].isdigit():
            flags.update(a[1:])
        else:
            rest.append(a)
    return flags, rest


def _bad_option(cmd, flags, allowed):
    """Return an error string if `flags` has an option we do not support."""
    bad = sorted(flags - set(allowed))
    if bad:
        return f"{cmd}: invalid option -- '{bad[0]}'\n"
    return ''


# --------------------------------------------------------------------------
# navigation
# --------------------------------------------------------------------------
def cmd_pwd(args, stdin):
    return os.getcwd() + '\n', '', 0


def cmd_cd(args, stdin):
    if len(args) > 1:
        return '', 'cd: too many arguments\n', 1
    target = args[0] if args else os.path.expanduser('~')
    try:
        os.chdir(target)
        return '', '', 0
    except OSError as e:
        return '', f'cd: {target}: {_msg(e)}\n', 1


# --------------------------------------------------------------------------
# ls  (supports -l and -a)
# --------------------------------------------------------------------------
def _long_line(path, name):
    st = os.lstat(path)
    when = time.strftime('%b %d %H:%M', time.localtime(st.st_mtime))
    return f'{stat.filemode(st.st_mode)} {st.st_nlink:>2} {st.st_size:>8} {when} {name}'


def cmd_ls(args, stdin):
    flags, paths = _split_opts(args)
    bad = _bad_option('ls', flags, 'la')
    if bad:
        return '', bad, 2
    long_fmt, show_all = 'l' in flags, 'a' in flags
    paths = paths or ['.']
    out, err, code = '', '', 0
    files, dirs = [], []
    for p in paths:
        if not os.path.lexists(p):
            err += f"ls: cannot access '{p}': No such file or directory\n"
            code = 1
        elif os.path.isdir(p):
            dirs.append(p)
        else:
            files.append(p)
    for f in files:
        out += (_long_line(f, f) if long_fmt else f) + '\n'
    for d in dirs:
        if len(paths) > 1:
            out += f'{d}:\n'
        try:
            names = sorted(os.listdir(d))
        except OSError as e:
            err += f"ls: cannot open directory '{d}': {_msg(e)}\n"
            code = 1
            continue
        if show_all:
            names = ['.', '..'] + names
        else:
            names = [n for n in names if not n.startswith('.')]
        for n in names:
            out += (_long_line(os.path.join(d, n), n) if long_fmt else n) + '\n'
    return out, err, code


# --------------------------------------------------------------------------
# creating / removing / copying / moving
# --------------------------------------------------------------------------
def cmd_mkdir(args, stdin):
    flags, names = _split_opts(args)
    bad = _bad_option('mkdir', flags, 'p')
    if bad:
        return '', bad, 2
    if not names:
        return '', 'usage: mkdir [-p] DIRECTORY...\n', 1
    err, code = '', 0
    for d in names:
        try:
            if 'p' in flags:
                os.makedirs(d, exist_ok=True)
            else:
                os.mkdir(d)
        except OSError as e:
            err += f"mkdir: cannot create directory '{d}': {_msg(e)}\n"
            code = 1
    return '', err, code


def cmd_rmdir(args, stdin):
    if not args:
        return '', 'usage: rmdir DIRECTORY...\n', 1
    err, code = '', 0
    for d in args:
        try:
            os.rmdir(d)
        except OSError as e:
            err += f"rmdir: failed to remove '{d}': {_msg(e)}\n"
            code = 1
    return '', err, code


def cmd_touch(args, stdin):
    if not args:
        return '', 'usage: touch FILE...\n', 1
    err, code = '', 0
    for f in args:
        try:
            if os.path.exists(f):
                os.utime(f, None)            # just update the time stamp
            else:
                open(f, 'a').close()
        except OSError as e:
            err += f"touch: cannot touch '{f}': {_msg(e)}\n"
            code = 1
    return '', err, code


def cmd_cp(args, stdin):
    flags, names = _split_opts(args)
    bad = _bad_option('cp', flags, 'r')
    if bad:
        return '', bad, 2
    if len(names) < 2:
        return '', 'usage: cp [-r] SOURCE... DEST\n', 1
    *sources, dest = names
    if len(sources) > 1 and not os.path.isdir(dest):
        return '', f"cp: target '{dest}' is not a directory\n", 1
    err, code = '', 0
    for s in sources:
        try:
            if os.path.isdir(s):
                if 'r' not in flags:
                    err += f"cp: -r not specified; omitting directory '{s}'\n"
                    code = 1
                    continue
                target = os.path.join(dest, os.path.basename(s.rstrip('/'))) \
                    if os.path.isdir(dest) else dest
                shutil.copytree(s, target)
            else:
                shutil.copy(s, dest)
        except (OSError, shutil.Error) as e:
            err += f"cp: cannot copy '{s}': {_msg(e)}\n"
            code = 1
    return '', err, code


def cmd_mv(args, stdin):
    if len(args) < 2:
        return '', 'usage: mv SOURCE... DEST\n', 1
    *sources, dest = args
    if len(sources) > 1 and not os.path.isdir(dest):
        return '', f"mv: target '{dest}' is not a directory\n", 1
    err, code = '', 0
    for s in sources:
        try:
            if not os.path.lexists(s):
                raise FileNotFoundError(2, 'No such file or directory')
            shutil.move(s, dest)
        except (OSError, shutil.Error) as e:
            err += f"mv: cannot move '{s}': {_msg(e)}\n"
            code = 1
    return '', err, code


def cmd_rm(args, stdin):
    flags, names = _split_opts(args)
    bad = _bad_option('rm', flags, 'rf')
    if bad:
        return '', bad, 2
    if not names:
        if 'f' in flags:
            return '', '', 0
        return '', 'usage: rm [-r] [-f] FILE...\n', 1
    err, code = '', 0
    for f in names:
        try:
            if not os.path.lexists(f):
                if 'f' not in flags:
                    err += f"rm: cannot remove '{f}': No such file or directory\n"
                    code = 1
            elif os.path.isdir(f) and not os.path.islink(f):
                if 'r' in flags:
                    shutil.rmtree(f)
                else:
                    err += f"rm: cannot remove '{f}': Is a directory (use -r)\n"
                    code = 1
            else:
                os.remove(f)
        except OSError as e:
            err += f"rm: cannot remove '{f}': {_msg(e)}\n"
            code = 1
    return '', err, code


# --------------------------------------------------------------------------
# reading / printing text
# --------------------------------------------------------------------------
def cmd_cat(args, stdin):
    flags, files = _split_opts(args)
    bad = _bad_option('cat', flags, 'n')
    if bad:
        return '', bad, 2
    if not files:                       # no file: read stdin (needed for pipes)
        files = ['-']
    out, err, code = '', '', 0
    for f in files:
        try:
            if f == '-':
                out += stdin
            else:
                with open(f, errors='replace') as fh:
                    out += fh.read()
        except OSError as e:
            err += f'cat: {f}: {_msg(e)}\n'
            code = 1
    if 'n' in flags:
        out = ''.join(f'{i:>6}\t{line}\n' for i, line in enumerate(out.splitlines(), 1))
    return out, err, code


def cmd_echo(args, stdin):
    newline = True
    if args and args[0] == '-n':
        newline, args = False, args[1:]
    return ' '.join(args) + ('\n' if newline else ''), '', 0


def cmd_wc(args, stdin):
    flags, files = _split_opts(args)
    bad = _bad_option('wc', flags, 'lwc')
    if bad:
        return '', bad, 2
    show = [k for k in 'lwc' if k in flags] or ['l', 'w', 'c']
    sources = files or ['-']
    out, err, code = '', '', 0
    for f in sources:
        try:
            if f == '-':
                text = stdin
            else:
                with open(f, errors='replace') as fh:
                    text = fh.read()
        except OSError as e:
            err += f'wc: {f}: {_msg(e)}\n'
            code = 1
            continue
        counts = {'l': text.count('\n'), 'w': len(text.split()), 'c': len(text)}
        out += ' '.join(f'{counts[k]:>6}' for k in show) + ('' if f == '-' else f' {f}') + '\n'
    return out, err, code


# --------------------------------------------------------------------------
# permissions
# --------------------------------------------------------------------------
def cmd_chmod(args, stdin):
    usage = 'usage: chmod MODE FILE...   (MODE is numeric, e.g. chmod 755 a.txt)\n'
    if len(args) < 2:
        return '', usage, 1
    mode, files = args[0], args[1:]
    if not re.fullmatch(r'[0-7]{3,4}', mode):
        return '', f"chmod: invalid mode: '{mode}'\n" + usage, 1
    err, code = '', 0
    for f in files:
        try:
            os.chmod(f, int(mode, 8))
        except OSError as e:
            err += f"chmod: cannot access '{f}': {_msg(e)}\n"
            code = 1
    return '', err, code


# --------------------------------------------------------------------------
# variables
# --------------------------------------------------------------------------
def cmd_env(args, stdin):
    return ''.join(f'{k}={v}\n' for k, v in sorted(variables.items())), '', 0


def cmd_unset(args, stdin):
    for name in args:
        variables.pop(name, None)
    return '', '', 0


# --------------------------------------------------------------------------
# true / false / test  (handy for && || and if/then/else)
# --------------------------------------------------------------------------
def cmd_true(args, stdin):
    return '', '', 0


def cmd_false(args, stdin):
    return '', '', 1


def _int(s):
    try:
        return int(s)
    except ValueError:
        raise ValueError('integer expression expected')


def _eval_test(a):
    if not a:
        return False
    if a[0] == '!':
        return not _eval_test(a[1:])
    if len(a) == 1:
        return a[0] != ''
    if len(a) == 2:
        op, x = a
        tests = {
            '-e': lambda: os.path.exists(x),
            '-f': lambda: os.path.isfile(x),
            '-d': lambda: os.path.isdir(x),
            '-r': lambda: os.access(x, os.R_OK),
            '-w': lambda: os.access(x, os.W_OK),
            '-x': lambda: os.access(x, os.X_OK),
            '-s': lambda: os.path.exists(x) and os.path.getsize(x) > 0,
            '-z': lambda: x == '',
            '-n': lambda: x != '',
        }
        if op not in tests:
            raise ValueError(f'unknown operator {op}')
        return tests[op]()
    if len(a) == 3:
        x, op, y = a
        if op in ('=', '=='):
            return x == y
        if op == '!=':
            return x != y
        nums = {'-eq': lambda: _int(x) == _int(y), '-ne': lambda: _int(x) != _int(y),
                '-lt': lambda: _int(x) < _int(y), '-le': lambda: _int(x) <= _int(y),
                '-gt': lambda: _int(x) > _int(y), '-ge': lambda: _int(x) >= _int(y)}
        if op not in nums:
            raise ValueError(f'unknown operator {op}')
        return nums[op]()
    raise ValueError('too many arguments')


def cmd_test(args, stdin):
    try:
        return '', '', (0 if _eval_test(list(args)) else 1)
    except ValueError as e:
        return '', f'test: {e}\n', 2


def cmd_bracket(args, stdin):
    """`[ -f file ]` is the same as `test -f file`."""
    if not args or args[-1] != ']':
        return '', "[: missing ']'\n", 2
    return cmd_test(args[:-1], stdin)


# --------------------------------------------------------------------------
# help
# --------------------------------------------------------------------------
HELP = """MiniShell commands
  Files        pwd  cd  ls [-la]  mkdir [-p]  rmdir  touch  cp [-r]  mv  rm [-rf]  cat [-n]  echo [-n]  wc [-lwc]
  Permissions  chmod MODE FILE   (numeric modes, e.g. chmod 755 a.txt;  ls -l shows them)
  Variables    NAME=value   echo $NAME   env   unset NAME   (also $? = last exit code)
  Conditions   cmd1 && cmd2   cmd1 || cmd2   cmd1 ; cmd2   if CMD; then CMD; else CMD; fi
               test / [ ] : true  false
  Redirection  >  >>  <  2>  2>>  2>&1        Pipes: cmd1 | cmd2 | cmd3
  Search       grep [-ivnocE F] PATTERN [FILE...]
  Scheduler    sched fcfs|sjn|priority|rr|mlq|mlfq|compare [--quantum N] [--trace] [FILE]
  Deadlock     deadlock detect FILE
               deadlock banker FILE [--request PID r1 r2 ...]
  Other        help  exit
"""


def cmd_help(args, stdin):
    return HELP, '', 0


BUILTINS = {
    'pwd': cmd_pwd, 'cd': cmd_cd, 'ls': cmd_ls, 'mkdir': cmd_mkdir,
    'rmdir': cmd_rmdir, 'touch': cmd_touch, 'cp': cmd_cp, 'mv': cmd_mv,
    'rm': cmd_rm, 'cat': cmd_cat, 'echo': cmd_echo, 'wc': cmd_wc,
    'chmod': cmd_chmod, 'env': cmd_env, 'unset': cmd_unset,
    'true': cmd_true, 'false': cmd_false, 'test': cmd_test, '[': cmd_bracket,
    'help': cmd_help,
}
