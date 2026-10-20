import copy
import importlib.util
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

from deps import needs_jsonschema, needs_pillow

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugins/image-studio/skills/image-loop/scripts'))
from controller import decide, repair_prompt
from review import check_file


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.brief = {'intent':'Make the bottle blue.', 'criteria':[
            {'id':'color','target':'bottle','kind':'requested','requirement':'Bottle is blue.'},
            {'id':'text','target':'headline','kind':'protected','requirement':'Keep exact headline.'}],
            'file_checks':{'width':1,'height':1,'format':'PNG','alpha_required':False}}
        self.report = {'criteria':[{'id':i,'status':'pass','evidence':'Visible evidence.','suggested_fix':''}
                                    for i in ['color','text']], 'summary':'Checked.'}
        self.checks = {'passed':True,'failures':[]}

    def test_accept_complete_pass(self):
        self.assertEqual(decide(self.brief,self.report,self.checks)['action'],'accepted_by_checks')
        self.assertEqual(decide(self.brief,self.report,self.checks)['ids'],[])  # same shape as the audit's decision

    def test_missing_duplicate_or_extra_ids_cannot_pass(self):
        for ids in [['color'],['color','color'],['color','text','invented']]:
            r=copy.deepcopy(self.report)
            r['criteria']=[dict(r['criteria'][0],id=i) for i in ids]
            self.assertEqual(decide(self.brief,r,self.checks)['action'],'stop_invalid_review')

    def test_uncertainty_holds_for_inspection(self):
        self.report['criteria'][1]['status']='uncertain'
        self.assertEqual(decide(self.brief,self.report,self.checks)['action'],'hold_for_inspection')

    def test_protected_failure_requires_repair(self):
        self.report['criteria'][1]['status']='fail'
        d=decide(self.brief,self.report,self.checks)
        self.assertEqual(d['action'],'repair')
        self.assertEqual(d['protected_failed'],['text'])
        self.assertIn('Keep exact headline.',repair_prompt(self.brief,self.report,d))

    def test_budget_stops(self):
        self.report['criteria'][0]['status']='fail'
        self.assertEqual(decide(self.brief,self.report,self.checks,3,3)['action'],'stop_budget')

    def test_repeated_failure_stops(self):
        self.report['criteria'][0]['status']='fail'
        self.assertEqual(decide(self.brief,self.report,self.checks,1,3,self.report)['action'],'stop_repeated_failure')

    def test_improving_failure_set_can_continue(self):
        previous=copy.deepcopy(self.report)
        for c in previous['criteria']:c['status']='fail'
        self.report['criteria'][0]['status']='fail'
        self.assertEqual(decide(self.brief,self.report,self.checks,1,3,previous)['action'],'repair')

    def test_file_failure_blocks_acceptance(self):
        self.assertEqual(decide(self.brief,self.report,{'passed':False,'failures':['wrong size']})['action'],'reject_technical')

    @needs_pillow
    def test_file_decode_and_alpha(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'fixture.png'
            Image.new('RGBA',(1,1),(0,0,0,255)).save(p)
            expected=dict(self.brief['file_checks'],alpha_required=True)
            self.assertFalse(check_file(p,expected)['passed'])
            Image.new('RGBA',(1,1),(0,0,0,0)).save(p)
            self.assertTrue(check_file(p,expected)['passed'])
            self.assertFalse(check_file(p,dict(expected,width=2))['passed'])

    def test_installer_refuses_overwrite(self):
        spec=importlib.util.spec_from_file_location('installer',ROOT/'scripts/install.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'skills'
            m.install(ROOT/'plugins/image-studio/skills',dest)
            marker=dest/'image-loop/keep.txt';marker.write_text('user work')
            with self.assertRaises(FileExistsError):m.install(ROOT/'plugins/image-studio/skills',dest)
            self.assertEqual(marker.read_text(),'user work')
            with self.assertRaises(ValueError):m.install(ROOT/'plugins/image-studio/skills',ROOT/'plugins/image-studio/skills',replace=True)

    @needs_jsonschema
    def test_extraction_dimension_guard(self):
        script=ROOT/'plugins/image-studio/skills/image-edit-map/scripts/validate_spec.py'
        image=ROOT/'examples/product/source.png'
        for filename, expected in [('raw-extraction.json',1),('image-spec.json',0)]:
            result=subprocess.run([sys.executable,str(script),str(ROOT/'examples/image-reverse-engineer'/filename),
                                   '--image',str(image)],capture_output=True,text=True)
            self.assertEqual(result.returncode,expected,result.stdout+result.stderr)

    @needs_jsonschema
    def test_protected_review_needs_source_before_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'review'
            result=subprocess.run([sys.executable,str(ROOT/'plugins/image-studio/skills/image-loop/scripts/review.py'),
                                   '--brief',str(ROOT/'examples/product/brief.json'),
                                   '--candidate',str(ROOT/'examples/product/source.png'),
                                   '--out',str(out),'--model','not-a-model'],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Protected comparison criteria require --source',result.stderr)
            self.assertFalse(out.exists())

    @needs_jsonschema
    @needs_pillow
    def test_codex_reviewer_gets_crops_and_no_image_generation(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp)
            log=tmp/'argv.txt'
            fake=tmp/'bin'/'codex'
            fake.parent.mkdir()
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "'+str(log)+'"\ncat > /dev/null\nexit 1\n')
            fake.chmod(0o755)
            crop=ROOT/'examples/product/source.png'
            env=dict(os.environ,PATH=str(fake.parent)+os.pathsep+os.environ.get('PATH',''))
            subprocess.run([sys.executable,str(ROOT/'plugins/image-studio/skills/image-loop/scripts/review.py'),
                            '--brief',str(ROOT/'examples/product/brief.json'),
                            '--source',str(ROOT/'examples/product/source.png'),
                            '--candidate',str(ROOT/'examples/product/source.png'),
                            '--crop',str(crop),'--out',str(tmp/'review'),'--model','m'],
                           capture_output=True,text=True,env=env)
            argv=log.read_text().splitlines()
            self.assertIn('image_generation',argv)
            self.assertEqual(argv[argv.index('image_generation')-1],'--disable')
            self.assertEqual(argv.count('--image'),3)
            prompt=(tmp/'review'/'reviewer-prompt.txt').read_text()
            self.assertIn('Image 3 is a 100% detail crop',prompt)


class FocusAndDependencyTests(unittest.TestCase):
    """One failure per repair round, prerequisites first, and no building on a regression."""

    def setUp(self):
        self.brief = {'name':'lantern', 'intent':'A red lantern hangs from a chain.', 'criteria':[
            {'id':'lantern','target':'lantern','kind':'requested','requirement':'A lantern is present.'},
            {'id':'red','target':'lantern','kind':'requested','requirement':'The lantern is red.','depends_on':['lantern']},
            {'id':'chain','target':'chain','kind':'requested','requirement':'The lantern hangs from a chain.'},
            {'id':'logo','target':'logo','kind':'protected','requirement':'Keep the logo.'}],
            'file_checks':{'width':None,'height':None,'format':None,'alpha_required':False}}
        self.checks = {'passed':True,'failures':[]}

    def report(self, **status):
        return {'criteria':[{'id':c['id'],'status':status.get(c['id'],'pass'),'evidence':'seen','suggested_fix':'fix '+c['id']}
                            for c in self.brief['criteria']], 'summary':'s'}

    def test_repair_focuses_one_failure_and_defers_the_rest(self):
        report = self.report(chain='fail', red='fail')
        d = decide(self.brief, report, self.checks)
        self.assertEqual(d['action'], 'repair')
        self.assertEqual(d['ids'], ['red', 'chain'])  # ids still lists every failure, like the audit
        self.assertEqual(d['focus'], 'red')
        prompt = repair_prompt(self.brief, report, d)
        self.assertIn('Correct this one observed failure:\n- red', prompt)
        self.assertIn('Leave these known failures for later rounds; do not work on them now:\n- chain', prompt)
        self.assertNotIn('fix chain', prompt)

    def test_protected_failure_is_fixed_first(self):
        d = decide(self.brief, self.report(chain='fail', logo='fail'), self.checks)
        self.assertEqual(d['focus'], 'logo')
        self.assertIn('never this candidate', d['start_from'])

    def test_child_of_a_failed_prerequisite_is_blocked_not_focused(self):
        d = decide(self.brief, self.report(lantern='fail', red='fail'), self.checks)
        self.assertEqual(d['focus'], 'lantern')
        self.assertEqual(d['blocked'], ['red'])

    def test_regression_restarts_from_the_previous_candidate(self):
        previous = self.report(red='fail', chain='fail')
        current = self.report(chain='fail', logo='fail')  # red fixed, but the logo broke
        d = decide(self.brief, current, self.checks, 1, 3, previous)
        self.assertEqual(d['action'], 'repair')
        self.assertEqual(d['regressed'], ['logo'])
        self.assertEqual(d['focus'], 'red')  # retry the previous round's focus on the previous candidate
        self.assertIn('previous start image', d['start_from'])
        prompt = repair_prompt(self.brief, current, d)
        self.assertIn('Correct this one observed failure:\n- red', prompt)
        self.assertIn('- logo: Keep the logo.', prompt.split('Keep every requirement below')[1])

    def test_regression_prompt_uses_the_previous_verdicts(self):
        previous = self.report(red='fail', chain='fail')
        d = decide(self.brief, self.report(logo='fail'), self.checks, 1, 3, previous)  # both fixed, logo broke
        self.assertEqual((d['focus'], d['regressed']), ('red', ['logo']))
        prompt = repair_prompt(self.brief, self.report(logo='fail'), d)
        self.assertIn('Leave these known failures for later rounds; do not work on them now:\n- chain', prompt)
        self.assertNotIn('- chain', prompt.split('Keep every requirement below')[1])
        self.assertIn('broke: logo', prompt)

    def test_restart_from_source_reapplies_every_requested_change(self):
        d = decide(self.brief, self.report(chain='fail', logo='fail'), self.checks)
        self.assertIsNone(d['start_review'])  # the source was never reviewed against the brief
        prompt = repair_prompt(self.brief, self.report(chain='fail', logo='fail'), d)
        self.assertIn('clean source', prompt)
        applied = prompt.split('Apply these requested changes:')[1].split('Keep these exactly')[0]
        for cid in ('lantern', 'red', 'chain'):
            self.assertIn('- '+cid+':', applied)
        self.assertNotIn('as it is now', prompt)

    @needs_jsonschema
    @needs_pillow
    def test_round_after_a_source_restart_is_not_compared_with_the_rejected_candidate(self):
        import json
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp/'brief.json').write_text(json.dumps(self.brief))
            Image.new('RGB', (4, 4)).save(tmp/'c.png')
            (tmp/'a.json').write_text(json.dumps(self.report(red='fail', logo='fail')))  # chain passed, logo damaged
            (tmp/'b.json').write_text(json.dumps(self.report(chain='fail')))  # from source: red and logo fine, chain not yet
            script = str(ROOT/'plugins/image-studio/skills/image-loop/scripts/review.py')
            base = ['--brief', str(tmp/'brief.json'), '--candidate', str(tmp/'c.png'), '--source', str(tmp/'c.png')]
            subprocess.run([sys.executable, script] + base + ['--report', str(tmp/'a.json'), '--out', str(tmp/'r0')], check=True,
                           capture_output=True)
            second = subprocess.run([sys.executable, script] + base + ['--report', str(tmp/'b.json'), '--out', str(tmp/'r1'),
                                    '--previous', str(tmp/'r0')], capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            d = json.loads((tmp/'r1'/'decision.json').read_text())
            self.assertEqual((d['regressed'], d['focus'], d['start_from']), ([], 'chain', 'this candidate'))

    def test_long_dependency_chain_has_no_recursion_error(self):
        brief = copy.deepcopy(self.brief)
        brief['criteria'] = [{'id':'c%d' % i,'target':'t','kind':'requested','requirement':'r',
                              'depends_on':['c%d' % (i-1)] if i else []} for i in range(3000)]
        report = {'criteria':[{'id':'c%d' % i,'status':'pass','evidence':'e','suggested_fix':''} for i in range(3000)],'summary':'s'}
        self.assertEqual(decide(brief, report, self.checks)['action'], 'accepted_by_checks')

    def test_no_regression_when_nothing_that_passed_broke(self):
        previous = self.report(red='fail', chain='fail')
        d = decide(self.brief, self.report(chain='fail'), self.checks, 1, 3, previous)
        self.assertEqual(d['regressed'], [])
        self.assertEqual(d['focus'], 'chain')
        self.assertNotIn('never this candidate', d['start_from'])

    def test_bad_dependencies_are_invalid(self):
        for deps in (['missing'], ['red'], ['lantern', 'lantern']):
            brief = copy.deepcopy(self.brief)
            brief['criteria'][1]['depends_on'] = deps
            self.assertEqual(decide(brief, self.report(), self.checks)['action'], 'stop_invalid_review', deps)
        brief = copy.deepcopy(self.brief)
        brief['criteria'][0]['depends_on'] = ['red']  # lantern -> red -> lantern
        self.assertIn('cycle', decide(brief, self.report(), self.checks)['reason'])

    @needs_jsonschema
    @needs_pillow
    def test_cli_rejects_a_dependency_cycle_before_reviewing(self):
        import json
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            brief = copy.deepcopy(self.brief)
            brief['criteria'][0]['depends_on'] = ['red']
            (tmp/'brief.json').write_text(json.dumps(brief))
            (tmp/'report.json').write_text(json.dumps(self.report()))
            Image.new('RGB', (4, 4)).save(tmp/'c.png')
            result = subprocess.run([sys.executable, str(ROOT/'plugins/image-studio/skills/image-loop/scripts/review.py'),
                                     '--brief', str(tmp/'brief.json'), '--candidate', str(tmp/'c.png'), '--source', str(tmp/'c.png'),
                                     '--report', str(tmp/'report.json'), '--out', str(tmp/'r0')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('cycle', result.stderr)
            self.assertFalse((tmp/'r0').exists())

    @needs_jsonschema
    @needs_pillow
    def test_cli_regression_prompt_uses_previous_evidence(self):
        import json
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp/'brief.json').write_text(json.dumps(self.brief))
            Image.new('RGB', (4, 4)).save(tmp/'c.png')
            prev = self.report(red='fail', chain='fail')
            prev['criteria'][1]['evidence'] = 'lantern is orange'
            (tmp/'p.json').write_text(json.dumps(prev))
            (tmp/'n.json').write_text(json.dumps(self.report(chain='fail', logo='fail')))
            script = str(ROOT/'plugins/image-studio/skills/image-loop/scripts/review.py')
            base = ['--brief', str(tmp/'brief.json'), '--candidate', str(tmp/'c.png'), '--source', str(tmp/'c.png')]
            first = subprocess.run([sys.executable, script] + base + ['--report', str(tmp/'p.json'), '--out', str(tmp/'r0')],
                                   capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            second = subprocess.run([sys.executable, script] + base + ['--report', str(tmp/'n.json'), '--out', str(tmp/'r1'),
                                    '--previous', str(tmp/'r0')], capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads((tmp/'r1'/'decision.json').read_text())['regressed'], ['logo'])
            self.assertIn('lantern is orange', (tmp/'r1'/'repair-prompt.txt').read_text())
            # Round 2 edited round 0's image; logo breaking again is still a regression against that image.
            (tmp/'n2.json').write_text(json.dumps(self.report(red='fail', chain='fail', logo='fail')))
            third = subprocess.run([sys.executable, script] + base + ['--report', str(tmp/'n2.json'), '--out', str(tmp/'r2'),
                                   '--previous', str(tmp/'r1')], capture_output=True, text=True)
            self.assertEqual(third.returncode, 0, third.stderr)
            self.assertEqual(json.loads((tmp/'r2'/'decision.json').read_text())['regressed'], ['logo'])


if __name__ == '__main__':
    unittest.main()
