"""Regression coverage for executable, parameter-preserving run distances."""
import unittest
from learner_models.run_sequence import compute_run_edit_distances, RunDistanceStream
from learner_models.distance import clear_cache


def workspace(value=100, orphan='', attached=True):
    drive = f'<block type="drive" id="d"><value name="DISTANCE"><shadow type="math_number" id="n"><field name="NUM">{value}</field></shadow></value></block>'
    stack = f'<block type="pg_events_when_started" id="s"><next>{drive}</next></block>' if attached else drive
    return f'<xml>{stack}{orphan}</xml>'


def events(*xmls):
    return [dict(event_type='runProject', ts=i, content=dict(playground='CastleCrasherPlus', project=dict(workspace=x))) for i,x in enumerate(xmls)]


class ScoringPolicyTests(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def score(self, a, b):
        return compute_run_edit_distances(events(a,b))['runs'][1]['edit_distance']

    def test_numeric_parameter(self):
        self.assertEqual(self.score(workspace(100),workspace(150)),1)

    def test_text_parameter(self):
        a=workspace('hello').replace('math_number','text').replace('NUM','TEXT')
        b=a.replace('hello','world')
        self.assertEqual(self.score(a,b),1)

    def test_orphan_add_delete_and_edit(self):
        a=workspace(orphan='<block type="turn" id="o"><field name="X">1</field></block>')
        b=a.replace('>1<','>2<')
        for x,y in [(workspace(),a),(a,workspace()),(a,b)]:
            self.assertEqual(self.score(x,y),0)

    def test_drive_insertion_cost_is_not_doubled(self):
        self.assertEqual(self.score('<xml><block type="pg_events_when_started" id="s"/></xml>',workspace()),1)

    def test_detached_program_is_empty_until_attached(self):
        self.assertEqual(self.score(workspace(100,attached=False),workspace(150,attached=False)),0)
        self.assertGreater(self.score(workspace(attached=False),workspace()),0)

    def test_multiple_start_stacks(self):
        extra=workspace(20).removeprefix('<xml>').removesuffix('</xml>').replace('id="s"','id="s2"').replace('id="d"','id="d2"').replace('id="n"','id="n2"')
        a=workspace(orphan=extra)
        self.assertEqual(self.score(a,a.replace('>20<','>30<')),1)

    def test_orphans_do_not_hit_size_guard(self):
        orphan=''.join(f'<block type="turn" id="o{i}"/>' for i in range(601))
        self.assertEqual(self.score(workspace(100,orphan),workspace(150,orphan)),1)

    def test_live_batch_parity_and_playground_reset(self):
        es=events(workspace(),workspace(150),workspace(200))
        es[-1]['content']['playground']='RoverRescue'
        stream=RunDistanceStream()
        for ev in es:stream.push(ev)
        self.assertEqual(stream.runs,compute_run_edit_distances(es)['runs'])
        self.assertEqual([r['edit_distance'] for r in stream.runs],[None,1,None])


if __name__=='__main__':
    unittest.main()
