# MiniShell - CmpSc 123 Group Project

MiniShell is a small Bash-like shell written in Python 3 that also contains
two operating-system simulators: a CPU scheduler (six algorithms) and a
deadlock simulator (detection + Banker's algorithm).

No third-party packages are needed. Only the standard library is used
(`re` for regular expressions; basic file I/O). All scheduling and deadlock
algorithms are written by us from scratch.

# Here is the link for our video presentation and peer evaluation:
https://drive.google.com/drive/folders/1ODKvSn1WMztgvAnQwgxccgoV8AynwvJf?usp=sharing

## Build and run

Requires Python 3.8 or newer. There is nothing to compile.

```bash
python3 minishell.py                  # interactive prompt (minishell>)
python3 minishell.py script.txt       # run the lines of a file
python3 minishell.py -c "ls | grep py"
python3 compare.py                    # Module 4 comparison tables
python3 compare.py --write report/results.md
python3 -m unittest discover -s tests # run all tests (68 tests)
python3 minishell.py tests/shell_demo.msh   # scripted demo
```

Type `help` inside the shell to list commands, `exit` to quit.

## Project layout

| File | What it does |
|---|---|
| `minishell.py` | main loop, tokenizer, `; && \|\|`, pipes, redirection, variables, `if/then/else` |
| `builtins_cmds.py` | file, directory, permission, variable commands |
| `grep_cmd.py` | grep-like search (basic text + regex bonus) |
| `scheduler.py` | PCB, six scheduling algorithms, `sched` command |
| `deadlock.py` | deadlock detection, Banker's algorithm, `deadlock` command |
| `compare.py` | Module 4: runs all algorithms on the same data |
| `samples/` | input files for the simulators (including edge cases) |
| `tests/` | unit tests and a demo script |
| `report/` | written report and generated `results.md` |

## Design 

Every command is a function `cmd(args, stdin_text) -> (stdout_text, stderr_text, exit_code)`.
Because all commands look the same, a pipe is just "stdout text of command 1 becomes
stdin text of command 2", and redirection is "write that text to a file".
`sched` and `deadlock` follow the same shape, so `sched rr p.txt > out.txt` and
`deadlock detect s.txt | grep P1` work automatically.
**Simplification:** pipe data is passed as text in memory, not through real
OS pipes. External programs are not run; unknown commands print `command not found`.

## Commands

### Files, directories, permissions
| Command | Notes |
|---|---|
| `pwd`, `cd [dir]` | `cd` with no argument goes home |
| `ls [-l] [-a] [paths]` | `-l` shows permissions like `-rwxr-xr-x`, size, date |
| `mkdir [-p] dir...`, `rmdir dir...` | |
| `touch file...` | creates the file or updates its time |
| `cp [-r] src... dest`, `mv src... dest` | |
| `rm [-r] [-f] file...` | |
| `cat [-n] [file...]` | no file = read stdin (so pipes work) |
| `echo [-n] text`, `wc [-lwc] [file]` | |
| `chmod MODE file...` | numeric modes only, e.g. `chmod 755 a.txt` |

### Variables and conditions
```
NAME=Ana          # assign
echo $NAME        # read ($NAME, ${NAME}, and $? = last exit code)
env               # list all variables
unset NAME
echo 'single quotes do not expand $NAME'   echo "double quotes do: $NAME"
cmd1 && cmd2      # run cmd2 only if cmd1 succeeded (exit code 0)
cmd1 || cmd2      # run cmd2 only if cmd1 failed
cmd1 ; cmd2       # always run both
if test -f a.txt; then echo yes; else echo no; fi   # bonus (one line, no nesting)
test / [ ... ]    # -e -f -d -r -w -x -s -z -n, a = b, a != b, -eq -ne -lt -le -gt -ge
true  false
```

### Redirection and pipes
```
cmd > file     cmd >> file     cmd < file
cmd 2> file    cmd 2>> file    cmd 2>&1
cmd1 | cmd2 | cmd3
```
`cmd > file 2>&1` sends both streams to the file. (`2>&1` always merges stderr into
stdout *before* the stdout redirect is applied.)

### grep
```
grep [-i] [-v] [-n] [-o] [-c] [-F] PATTERN [FILE...]
```
Prints the lines containing `PATTERN`. The pattern is a regular expression (bonus):
`.`  `[a-z]`  `*`  `+`  `?`  `\.` escapes and `( )` groups. `-F` = plain text,
`-i` ignore case, `-v` invert, `-n` line numbers, `-o` only the matching part,
`-c` count. With no FILE it reads stdin. Exit code 0 = match, 1 = no match, 2 = error.

### Scheduler: `sched`
```
sched ALGORITHM [--quantum N] [--trace] [FILE]
ALGORITHM = fcfs | sjn | priority | rr | mlq | mlfq | compare
```
Examples:
```
sched fcfs samples/processes.txt
sched rr --quantum 4 samples/processes.txt
sched mlfq --trace samples/processes.txt     # also prints every state change
sched compare samples/processes.txt          # all six side by side
cat samples/processes.txt | sched sjn        # input from a pipe
```
For each algorithm it prints the PCB table (before and after), a text Gantt chart,
a per-process table (completion, turnaround, waiting), the averages, context
switches and CPU utilization.

**Process file format** (`#` starts a comment, priority is optional, default 0):
```
# pid arrival burst priority
P1 0 8 2
P2 1 4 1
```
**Conventions**
* **Lower priority number = higher priority.**
* FCFS, SJN and Priority are non-preemptive. Round-Robin: new arrivals join the queue
  *before* the process that was just preempted.
* **MLQ:** Queue 1 = priority 1-2, Round-Robin (quantum 4 or `--quantum`);
  Queue 2 = priority 3+, FCFS. Queue 1 always runs first and pauses Queue 2.
  A process never changes queue.
* **MLFQ:** Q0 Round-Robin quantum 2, Q1 Round-Robin quantum 4, Q2 FCFS.
  (`--quantum Q` sets Q0 = Q and Q1 = 2Q.) Using a whole quantum without finishing
  demotes a process one level. A new arrival (enters Q0) preempts a process in Q1/Q2;
  the preempted process is *not* demoted.
* PCB states shown: New, Ready, Running, Terminated. `Waiting` (blocked on I/O) is not
  used because the model has no I/O.
* Formulas: Turnaround = Completion - Arrival; Waiting = Turnaround - Burst.

### Deadlock: `deadlock`
```
deadlock detect FILE
deadlock banker FILE [--request PID r1 r2 ... rm]
```
Examples:
```
deadlock detect samples/system_unsafe.txt
deadlock banker samples/system_safe.txt
deadlock banker samples/system_safe.txt --request 1 1 0 2   # P1 asks for (1,0,2)
```
`banker` prints the Need matrix, each step of the safety check, and the safe sequence
(or says the state is unsafe). With `--request` it also shows the three Banker's checks
(request <= need, request <= available, pretend-grant + safety check) and says
GRANTED, DENIED or WAIT. `detect` lists deadlocked processes and prints a
**recovery suggestion** (bonus): terminate the stuck process holding the most
resources, re-run detection, repeat.

Exit codes: 0 = no deadlock / safe / granted, 1 = deadlock / unsafe / denied, 2 = bad input
(so `deadlock banker s.txt && echo safe` works).

**System file format**
```
5 3            # number of processes, number of resource types
Allocation     # 5 rows of 3 numbers
...
Max            # 5 rows
...
Request        # OPTIONAL: what each process is waiting for (used by `detect`;
...            #   if missing, detect uses Need = Max - Allocation)
Available      # 1 row
3 3 2
```

## Tests

`python3 -m unittest discover -s tests` runs 68 tests. Expected scheduling numbers were
worked out by hand; the Banker's tests use the well-known textbook example
(safe sequence P1, P3, P4, P0, P2).

| Area | Test 1 | Test 2 | Edge cases |
|---|---|---|---|
| Scheduler | `processes_all0.txt` (all arrive at 0) | `processes.txt` (staggered) / `processes_mixed.txt` | `processes_single.txt`, `processes_empty.txt`, `processes_gap.txt` (idle CPU), `processes_bad.txt` (error) |
| Deadlock | `system_safe.txt` | `system_unsafe.txt` | `system_single.txt`, `system_nothing.txt`, `system_bad.txt` (error), zero processes |
| Shell | pipes + redirects | `&&` `\|\|` `;` variables, if/else | syntax errors, unknown command, missing files |

## Team

| Role | Member |
|---|---|
| Shell Lead (Module 1, integration) | Ronald Sagsagat |
| Scheduler Lead (Module 2) | Leah Orenza |
| Resources Lead (Module 3) | Oryza Maize Maligsay |
| Docs and Testing Lead (grep, tests, Module 4, report) | Tyrone Clyde Buduan |
