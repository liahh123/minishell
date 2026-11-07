"""Scheduler tests. Expected numbers were worked out BY HAND (see comments)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import scheduler as S

SAMPLES = os.path.join(os.path.dirname(__file__), '..', 'samples')
def load(name): return S.load(os.path.join(SAMPLES, name))
def run(key, name, q=None): return S.simulate(key, load(name), q)


class TestStaggered(unittest.TestCase):          # samples/processes.txt
    # P1 0/8, P2 1/4, P3 2/9, P4 3/5
    def test_fcfs(self):          # completions 8,12,21,26 -> waits 0,7,10,18
        r = run('fcfs', 'processes.txt')
        self.assertEqual((r['avg_wait'], r['avg_turn']), (8.75, 15.25))
        self.assertEqual(r['timeline'], [('P1', 0, 8), ('P2', 8, 12), ('P3', 12, 21), ('P4', 21, 26)])

    def test_sjn(self):           # P1, then P2(4), P4(5), P3(9): waits 0,7,15,9
        r = run('sjn', 'processes.txt')
        self.assertEqual([b[0] for b in r['timeline']], ['P1', 'P2', 'P4', 'P3'])
        self.assertEqual((r['avg_wait'], r['avg_turn']), (7.75, 14.25))

    def test_priority(self):      # lower number first: P1, P2(1), P4(2), P3(3)
        r = run('priority', 'processes.txt')
        self.assertEqual([b[0] for b in r['timeline']], ['P1', 'P2', 'P4', 'P3'])
        self.assertEqual((r['avg_wait'], r['avg_turn']), (7.75, 14.25))

    def test_round_robin(self):   # q=4 completions P1 20, P2 8, P3 26, P4 25 -> waits 12,3,15,17
        r = run('rr', 'processes.txt', 4)
        self.assertEqual([r['procs'][i].completion for i in range(4)], [20, 8, 26, 25])
        self.assertEqual((r['avg_wait'], r['avg_turn']), (11.75, 18.25))


class TestAllArriveAtZero(unittest.TestCase):    # samples/processes_all0.txt, bursts 10,1,2,1,5
    def test_fcfs(self):          # waits 0,10,11,13,14 -> 48/5
        self.assertAlmostEqual(run('fcfs', 'processes_all0.txt')['avg_wait'], 9.6)

    def test_sjn(self):           # order P2,P4,P3,P5,P1 -> waits 0,1,2,4,9 -> 16/5
        r = run('sjn', 'processes_all0.txt')
        self.assertAlmostEqual(r['avg_wait'], 3.2)
        self.assertEqual([b[0] for b in r['timeline']], ['P2', 'P4', 'P3', 'P5', 'P1'])

    def test_priority(self):      # order P2,P5,P1,P3,P4 -> waits 0,1,6,16,18 -> 41/5
        self.assertAlmostEqual(run('priority', 'processes_all0.txt')['avg_wait'], 8.2)


class TestEdgeCases(unittest.TestCase):
    def test_single_process_all_algorithms(self):
        for key in S.ALGOS:
            r = run(key, 'processes_single.txt')
            self.assertEqual(r['avg_wait'], 0, key)
            self.assertEqual(r['avg_turn'], 5, key)
            self.assertEqual(r['timeline'], [('P1', 0, 5)], key)

    def test_idle_gap(self):      # P1 0-3, idle 3-10, P2 10-14, P3 14-16 under FCFS
        r = run('fcfs', 'processes_gap.txt')
        self.assertEqual(r['timeline'], [('P1', 0, 3), ('P2', 10, 14), ('P3', 14, 16)])
        self.assertIn('idle', S.render_gantt(S.gantt_blocks(r['timeline'])))
        self.assertAlmostEqual(r['avg_wait'], 1.0)     # waits 0,0,3

    def test_idle_gap_all_algorithms_finish(self):
        for key in S.ALGOS:
            r = run(key, 'processes_gap.txt')
            self.assertTrue(all(p.state == 'Terminated' for p in r['procs']), key)
            self.assertEqual(r['makespan'], 16, key)

    def test_empty_queue(self):
        self.assertEqual(load('processes_empty.txt'), [])
        out, err, code = S.cmd_sched(['fcfs', os.path.join(SAMPLES, 'processes_empty.txt')], '')
        self.assertEqual(code, 0)
        self.assertIn('empty', out)

    def test_bad_input_is_an_error_not_a_crash(self):
        out, err, code = S.cmd_sched(['fcfs', os.path.join(SAMPLES, 'processes_bad.txt')], '')
        self.assertEqual(code, 1)
        self.assertIn('line 2', err)

    def test_missing_file_and_bad_args(self):
        self.assertEqual(S.cmd_sched(['fcfs', 'nope.txt'], '')[2], 1)
        self.assertEqual(S.cmd_sched(['bogus', 'x'], '')[2], 1)
        self.assertEqual(S.cmd_sched(['rr', '--quantum', '0', 'x'], '')[2], 1)
        self.assertEqual(S.cmd_sched([], '')[2], 1)


class TestInvariants(unittest.TestCase):
    def test_every_algorithm_gives_a_valid_schedule(self):
        for name in ('processes.txt', 'processes_all0.txt', 'processes_mixed.txt', 'processes_gap.txt'):
            for key in S.ALGOS:
                r = run(key, name)
                bursts = {p.pid: p.burst for p in r['procs']}
                ran = {}
                last_end = 0
                for pid, s, e in r['timeline']:
                    self.assertGreaterEqual(s, last_end, (name, key))        # CPU runs one thing at a time
                    ran[pid] = ran.get(pid, 0) + (e - s)
                    last_end = e
                    arrival = next(p.arrival for p in r['procs'] if p.pid == pid)
                    self.assertGreaterEqual(s, arrival, (name, key))         # nobody runs before arriving
                self.assertEqual(ran, bursts, (name, key))                   # everyone got exactly its burst
                for p in r['procs']:
                    self.assertGreaterEqual(r['waiting'][p.pid], 0, (name, key))

    def test_runs_do_not_share_state(self):
        procs = load('processes.txt')
        a = S.simulate('rr', procs, 4)['avg_wait']
        S.simulate('fcfs', procs)
        self.assertEqual(S.simulate('rr', procs, 4)['avg_wait'], a)
        self.assertTrue(all(p.state == 'New' for p in procs))

    def test_mlq_queue1_beats_queue2(self):
        # P1 (priority 5, FCFS queue) is running when P2 (priority 1) arrives at t=2: P2 must preempt.
        procs = S.parse_processes('P1 0 6 5\nP2 2 2 1\n')
        tl = S.merge(S.mlq(procs))
        self.assertEqual(tl, [('P1', 0, 2), ('P2', 2, 4), ('P1', 4, 8)])

    def test_mlfq_demotion(self):
        # q0=2, q1=4: P1 (burst 7) runs 0-2 (Q0), then 2-6 (Q1), then 6-7 (Q2)
        procs = S.parse_processes('P1 0 7 1\n')
        self.assertEqual(S.merge(S.mlfq(procs)), [('P1', 0, 7)])
        procs = S.parse_processes('P1 0 7 1\nP2 1 1 1\n')
        tl = S.mlfq(procs)
        self.assertEqual(tl[:3], [('P1', 0, 2), ('P2', 2, 3), ('P1', 3, 7)])


if __name__ == '__main__':
    unittest.main()
