"""Deadlock tests: hand-checked against the well-known textbook example."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import deadlock as D

SAMPLES = os.path.join(os.path.dirname(__file__), '..', 'samples')
def system(name):
    with open(os.path.join(SAMPLES, name)) as f:
        return D.parse_system(f.read())
def path(name): return os.path.join(SAMPLES, name)


class TestBanker(unittest.TestCase):
    def test_safe_state_and_sequence(self):      # textbook: <P1, P3, P4, P0, P2>
        s = system('system_safe.txt')
        safe, seq, _ = D.safety(s['alloc'], s['need'], s['avail'])
        self.assertTrue(safe)
        self.assertEqual(seq, [1, 3, 4, 0, 2])

    def test_need_matrix(self):
        s = system('system_safe.txt')
        self.assertEqual(s['need'][0], [7, 4, 3])
        self.assertEqual(s['need'][1], [1, 2, 2])

    def test_unsafe_state(self):
        s = system('system_unsafe.txt')
        safe, seq, _ = D.safety(s['alloc'], s['need'], s['avail'])
        self.assertFalse(safe)
        self.assertEqual(seq, [3])               # only P3 (holds nothing, needs nothing) can finish

    def test_request_granted(self):              # textbook: P1 requests (1,0,2) -> granted
        d, _ = D.try_request(system('system_safe.txt'), 1, [1, 0, 2])
        self.assertEqual(d, 'granted')

    def test_request_denied_unsafe(self):        # textbook: P4 requests (3,3,0) -> would be unsafe
        self.assertEqual(D.try_request(system('system_safe.txt'), 4, [3, 3, 0])[0], 'denied')

    def test_textbook_sequence_after_p1_is_granted(self):
        # After P1's (1,0,2) is granted: Available = 2 3 0.
        s = system('system_safe.txt')
        s['alloc'][1], s['need'][1], s['avail'] = [3, 0, 2], [0, 2, 0], [2, 3, 0]
        self.assertEqual(D.try_request(s, 4, [3, 3, 0])[0], 'wait')     # not enough available
        self.assertEqual(D.try_request(s, 0, [0, 2, 0])[0], 'denied')   # available, but unsafe
        # ...while in the ORIGINAL state P0's (0,2,0) is fine (checked by hand: P3,P1,P2,P4,P0 can finish)
        self.assertEqual(D.try_request(system('system_safe.txt'), 0, [0, 2, 0])[0], 'granted')

    def test_request_exceeds_available_must_wait(self):
        self.assertEqual(D.try_request(system('system_safe.txt'), 0, [4, 0, 0])[0], 'wait')

    def test_request_exceeds_need_is_error(self):
        self.assertEqual(D.try_request(system('system_safe.txt'), 1, [2, 0, 0])[0], 'error')

    def test_request_does_not_change_the_system(self):
        s = system('system_safe.txt')
        before = (s['avail'][:], [r[:] for r in s['alloc']])
        D.try_request(s, 1, [1, 0, 2])
        self.assertEqual((s['avail'], s['alloc']), before)


class TestDetection(unittest.TestCase):
    def test_deadlock_found(self):
        s = system('system_unsafe.txt')
        self.assertEqual(D.detect(s['alloc'], s['need'], s['avail']), [0, 1, 2])

    def test_no_deadlock_in_safe_state(self):
        s = system('system_safe.txt')
        self.assertEqual(D.detect(s['alloc'], s['need'], s['avail']), [])

    def test_recovery_clears_deadlock(self):
        s = system('system_unsafe.txt')
        killed, _ = D.recovery(s['alloc'], s['need'], s['avail'])
        self.assertEqual(len(killed), 1)         # killing one process of the cycle is enough

    def test_explicit_request_matrix_is_used(self):
        text = "2 1\nAllocation\n1\n1\nRequest\n1\n1\nAvailable\n0\n"
        s = D.parse_system(text)
        self.assertEqual(D.detect(s['alloc'], s['request'], s['avail']), [0, 1])


class TestEdgeCasesAndCommand(unittest.TestCase):
    def test_single_process(self):
        out, err, code = D.cmd_deadlock(['banker', path('system_single.txt')], '')
        self.assertEqual(code, 0); self.assertIn('P0', out)

    def test_nothing_allocated_is_safe(self):
        out, err, code = D.cmd_deadlock(['detect', path('system_nothing.txt')], '')
        self.assertEqual(code, 0); self.assertIn('NO DEADLOCK', out)

    def test_zero_processes(self):
        text = "0 2\nAllocation\nMax\nAvailable\n1 1\n"
        out, err, code = D.cmd_deadlock(['banker'], text)           # system description piped in via stdin
        self.assertEqual(code, 0); self.assertIn('SAFE', out)

    def test_exit_codes(self):
        self.assertEqual(D.cmd_deadlock(['detect', path('system_safe.txt')], '')[2], 0)
        self.assertEqual(D.cmd_deadlock(['detect', path('system_unsafe.txt')], '')[2], 1)
        self.assertEqual(D.cmd_deadlock(['banker', path('system_unsafe.txt')], '')[2], 1)

    def test_command_request_option(self):
        out, err, code = D.cmd_deadlock(['banker', path('system_safe.txt'), '--request', '1', '1', '0', '2'], '')
        self.assertEqual(code, 0); self.assertIn('GRANTED', out)
        out, err, code = D.cmd_deadlock(['banker', path('system_safe.txt'), '--request', 'P4', '3', '3', '0'], '')
        self.assertEqual(code, 1); self.assertIn('DENIED', out)

    def test_errors_do_not_crash(self):
        self.assertEqual(D.cmd_deadlock(['detect', 'nope.txt'], '')[2], 2)
        self.assertEqual(D.cmd_deadlock(['detect', path('system_bad.txt')], '')[2], 2)
        self.assertEqual(D.cmd_deadlock(['banker', path('system_safe.txt'), '--request', '9', '1', '1', '1'], '')[2], 2)
        self.assertEqual(D.cmd_deadlock(['banker', path('system_safe.txt'), '--request', '1', '1'], '')[2], 2)
        self.assertEqual(D.cmd_deadlock(['bogus'], '')[2], 2)


if __name__ == '__main__':
    unittest.main()
