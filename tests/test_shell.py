"""Shell tests: run real MiniShell scripts in a temporary folder and check the output."""
import os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SHELL = os.path.join(HERE, '..', 'minishell.py')
SAMPLES = os.path.abspath(os.path.join(HERE, '..', 'samples'))


def sh(script, stdin=None):
    """Run a multi-line script in a fresh temp dir. Returns (stdout, stderr, exit_code)."""
    with tempfile.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, SHELL, '-c', script.replace('$S', SAMPLES)],
                           cwd=d, capture_output=True, text=True, input=stdin, timeout=20)
        return r.stdout, r.stderr, r.returncode


class TestRedirectionAndPipes(unittest.TestCase):
    def test_redirect_out_append_in(self):
        out, err, _ = sh("echo hello > a.txt\ncat a.txt\necho more >> a.txt\ncat a.txt\ncat < a.txt")
        self.assertEqual(out, "hello\nhello\nmore\nhello\nmore\n")

    def test_pipe_two_commands(self):
        out, _, _ = sh("touch a.txt b.log c.txt\nls | grep txt")
        self.assertEqual(out, "a.txt\nc.txt\n")

    def test_pipe_three_commands(self):
        out, _, _ = sh("echo one > f\necho two >> f\necho three >> f\ncat f | grep t | wc -l")
        self.assertEqual(out.split(), ['2'])

    def test_stdin_redirect_into_pipe(self):
        out, _, _ = sh("echo hello > a.txt\necho more >> a.txt\ncat < a.txt | grep more")
        self.assertEqual(out, "more\n")

    def test_stderr_redirect(self):
        out, err, _ = sh("cat nofile 2> e.txt\ncat e.txt")
        self.assertEqual(err, "")
        self.assertIn("nofile: No such file or directory", out)

    def test_stderr_to_stdout_in_pipe(self):
        out, err, _ = sh("cat nofile 2>&1 | grep nofile")
        self.assertIn("nofile", out)
        self.assertEqual(err, "")

    def test_without_redirect_errors_go_to_stderr(self):
        out, err, _ = sh("cat nofile")
        self.assertEqual(out, "")
        self.assertIn("No such file", err)

    def test_redirect_both_to_file(self):
        out, _, _ = sh("cat nofile > both.txt 2>&1\ncat both.txt")
        self.assertIn("nofile", out)

    def test_number_two_is_a_normal_word(self):
        out, _, _ = sh("echo 2 > n.txt\ncat n.txt")
        self.assertEqual(out, "2\n")


class TestVariablesAndConditions(unittest.TestCase):
    def test_variables(self):
        out, _, _ = sh("NAME=Ana\necho $NAME\necho \"hi $NAME\"\necho 'no $NAME'\nenv")
        self.assertEqual(out, "Ana\nhi Ana\nno $NAME\nNAME=Ana\n")

    def test_assignment_and_use_on_one_line(self):
        out, _, _ = sh("X=5; echo $X")
        self.assertEqual(out, "5\n")

    def test_and_or_semicolon(self):
        out, err, _ = sh("mkdir x && echo ok\nrmdir nothere || echo failed\necho a ; echo b\nfalse && echo no\ntrue || echo no")
        self.assertEqual(out, "ok\nfailed\na\nb\n")

    def test_exit_status_variable(self):
        out, _, _ = sh("false\necho $?\ntrue\necho $?")
        self.assertEqual(out, "1\n0\n")

    def test_if_then_else(self):
        out, _, _ = sh("touch f\nif test -f f; then echo yes; else echo no; fi\n"
                       "if test -f g; then echo yes; else echo no; fi\n"
                       "if true; then echo only; fi; echo after")
        self.assertEqual(out, "yes\nno\nonly\nafter\n")

    def test_bracket_test(self):
        out, _, _ = sh("[ 3 -lt 5 ] && echo less\n[ a = b ] || echo differ")
        self.assertEqual(out, "less\ndiffer\n")


class TestBuiltins(unittest.TestCase):
    def test_file_commands(self):
        out, err, _ = sh("mkdir d\ntouch d/a\ncp d/a d/b\nmv d/b d/c\nls d\nrm d/a\nls d\nrm -r d\nls")
        self.assertEqual(out, "a\nc\nc\n")   # ls d, then (after rm d/a) ls d, then ls (empty)
        self.assertEqual(err, "")

    def test_cd_and_pwd(self):
        out, _, _ = sh("mkdir sub\ncd sub\npwd")
        self.assertTrue(out.strip().endswith("sub"))

    def test_chmod_and_ls_l(self):
        out, _, _ = sh("touch a\nchmod 755 a\nls -l")
        self.assertTrue(out.startswith("-rwxr-xr-x"))
        out, _, _ = sh("touch a\nchmod 600 a\nls -l")
        self.assertTrue(out.startswith("-rw-------"))

    def test_grep_features(self):
        out, _, _ = sh("echo apple > f\necho banana >> f\necho Cherry >> f\n"
                       "grep an f\ngrep -i cherry f\ngrep -v an f\ngrep -n an f\n"
                       "grep '^[a-b]' f\ngrep 'an+a' f\ngrep -F 'a.p' f || echo none")
        self.assertEqual(out, "banana\nCherry\napple\nCherry\n2:banana\napple\nbanana\nbanana\nnone\n")

    def test_grep_exit_codes(self):
        out, _, _ = sh("echo abc > f\ngrep zzz f\necho $?\ngrep abc f\necho $?")
        self.assertEqual(out, "1\nabc\n0\n")


class TestErrorHandling(unittest.TestCase):
    def test_unknown_command(self):
        out, err, _ = sh("foobar\necho $?")
        self.assertIn("foobar: command not found", err)
        self.assertEqual(out, "127\n")

    def test_missing_files_and_bad_arguments(self):
        _, err, _ = sh("cat nofile\nls nodir\nrm nofile\ncd nodir\nchmod 999 x\nchmod\nmkdir\ncp onlyone")
        for text in ("cat: nofile", "ls: cannot access 'nodir'", "rm: cannot remove 'nofile'",
                     "cd: nodir", "invalid mode", "usage: chmod", "usage: mkdir", "usage: cp"):
            self.assertIn(text, err)

    def test_syntax_errors_do_not_crash(self):
        for bad in ("echo hi >", "| ls", "ls ||", "echo 'unterminated", "echo hi &", "if true; then echo x", "; ls"):
            out, err, code = sh(bad + "\necho still-alive")
            self.assertIn("still-alive", out, bad)
            self.assertIn("minishell:", err, bad)

    def test_shell_survives_a_failing_command_in_the_middle(self):
        out, err, _ = sh("foobar\ncat nofile\necho alive")
        self.assertEqual(out, "alive\n")

    def test_missing_input_redirect_file(self):
        out, err, _ = sh("cat < nofile")
        self.assertIn("nofile", err)

    def test_exit_stops_the_shell(self):
        out, _, code = sh("echo one\nexit\necho two")
        self.assertEqual(out, "one\n")

    def test_interactive_session_via_stdin(self):
        r = subprocess.run([sys.executable, SHELL], input="echo hi\nfoobar\nexit\necho never\n",
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.stdout, "hi\n")
        self.assertIn("command not found", r.stderr)


class TestSimulatorsInsideTheShell(unittest.TestCase):
    def test_sched_through_redirect_and_pipe(self):
        out, _, _ = sh("sched rr --quantum 4 $S/processes.txt > result.txt\ngrep Average result.txt")
        self.assertIn("Average waiting time    : 11.75", out)
        out, _, _ = sh("sched sjn $S/processes.txt | grep 'Average waiting'")
        self.assertEqual(out.strip(), "Average waiting time    : 7.75")

    def test_sched_reads_stdin_pipe(self):
        out, _, _ = sh("cat $S/processes.txt | sched fcfs | grep Average")
        self.assertIn("8.75", out)

    def test_sched_error_in_shell(self):
        out, err, _ = sh("sched fcfs nofile.txt\nsched wrong $S/processes.txt\nsched rr --quantum x $S/processes.txt")
        self.assertIn("nofile.txt", err)
        self.assertIn("unknown algorithm", err)
        self.assertIn("bad quantum", err)

    def test_deadlock_in_shell(self):
        out, _, _ = sh("deadlock banker $S/system_safe.txt | grep Result")
        self.assertIn("SAFE", out)
        self.assertIn("P1 -> P3 -> P4 -> P0 -> P2", out)
        out, _, _ = sh("deadlock detect $S/system_unsafe.txt | grep DEADLOCK")
        self.assertIn("P0, P1, P2", out)

    def test_deadlock_exit_code_in_conditionals(self):
        out, _, _ = sh("deadlock banker $S/system_safe.txt > /dev/null && echo safe\n"
                       "deadlock banker $S/system_unsafe.txt > /dev/null || echo unsafe")
        self.assertEqual(out, "safe\nunsafe\n")


if __name__ == '__main__':
    unittest.main()
