"""Controller service lifecycle tests. Never call a model or run model inference."""
import argparse
import fcntl
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import continuation_job as job


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run = pathlib.Path(self.temp.name)
        job.write(self.run/'state.json', {'id':'test','status':'queued','attempt':1})
        job.write(self.run/'request.json', {'request':{'timeout_seconds':3}})
        self.lock = (self.run/'lease').open('w+')
        self.addCleanup(self.lock.close)
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def supervise_script(self, script):
        original = subprocess.Popen
        def launch(_command, **kwargs):
            return original([sys.executable, '-c', script, str(self.run)], **kwargs)
        with patch.object(job.subprocess, 'Popen', side_effect=launch):
            job.supervise(self.run, self.run, pathlib.Path('/unused/nc'), False, self.lock.fileno())
        return job.read(self.run/'state.json')

    def test_success_is_not_an_evaluation_or_publication_claim(self):
        state = self.supervise_script("import sys,pathlib,json; p=pathlib.Path(sys.argv[1]); (p/'result.json').write_text(json.dumps({'candidate':'frozen','evaluation':None}))")
        self.assertEqual(state['status'], 'completed')
        self.assertIsNone(state['result']['evaluation'])
        self.assertIn('ready for final evaluation', state['message'])

    def test_nonzero_exit_is_failed_with_no_provider_output_in_status(self):
        state = self.supervise_script("import sys; print('private diagnostic',file=sys.stderr); sys.exit(2)")
        self.assertEqual(state['status'], 'failed')
        self.assertNotIn('private diagnostic', json.dumps(state))

    def test_cancel_stops_work_and_retains_evidence(self):
        state = self.supervise_script("import sys,pathlib,time; p=pathlib.Path(sys.argv[1]); (p/'transcript').write_text('retained'); (p/'cancel.json').write_text('{}'); time.sleep(30)")
        self.assertEqual(state['status'], 'cancelled')
        self.assertEqual((self.run/'transcript').read_text(), 'retained')

    def test_deadline_stops_silent_child(self):
        job.write(self.run/'request.json', {'request':{'timeout_seconds':0.1}})
        state = self.supervise_script('import time; time.sleep(30)')
        self.assertEqual(state['status'], 'timed_out')

    def test_cancel_before_start_does_not_spawn(self):
        job.write(self.run/'cancel.json', {})
        with patch.object(job.subprocess, 'Popen') as launch:
            job.supervise(self.run,self.run,pathlib.Path('/unused'),False,self.lock.fileno())
        launch.assert_not_called()
        self.assertEqual(job.read(self.run/'state.json')['status'], 'cancelled')

    def test_child_inherits_execution_lease(self):
        state = self.supervise_script("import sys,os,json,pathlib; p=pathlib.Path(sys.argv[1]); fd=int(os.environ['NC_CONTINUATION_LEASE_FD']); os.fstat(fd); (p/'result.json').write_text(json.dumps({'lease_inherited':True}))")
        self.assertTrue(state['result']['lease_inherited'])


class Inputs(unittest.TestCase):
    def test_import_prepares_real_spec_without_evaluation(self):
        from weight_experiment import experiment, EVALUATOR
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp); home=root/'home'; home.mkdir()
            directory=root/'task'; (directory/'model').mkdir(parents=True)
            session_dir=root/'session';session_dir.mkdir()
            for name in ['config','development','heldout','policy','source']:
                job.write(directory/(name+'.json'),{'max_samples':1,'metric':'accuracy/v1'})
            for name in ['config','tokenizer','tokenizer_config','special_tokens_map']:
                job.write(directory/'model'/(name+'.json'),{})
            (directory/'model/model.safetensors').write_bytes(b'base')
            (session_dir/'candidate.safetensors').write_bytes(b'candidate')
            (session_dir/'transcript.jsonl').write_text('')
            commitment={name+'_sha256':job.sha(directory/(name+'.json')) for name in ['config','development','heldout','policy']}
            commitment.update(target_sha256=job.sha(directory/'model/model.safetensors'),controller='test',backend='codex')
            job.write(session_dir/'commitment.json',commitment)
            job.write(session_dir/'session.json',{'commitment':commitment,'candidate_sha256':job.sha(session_dir/'candidate.safetensors'),
                'transcript_sha256':job.sha(session_dir/'transcript.jsonl'),'selected':{'hypothesis':'test'},'changed_parameters':1})
            registrations=[]; commands=[]
            def nc(_home,command,*args):
                commands.append(command)
                if command=='register':
                    registrations.append(args);return {'checkpoint':('b' if len(registrations)==1 else 'c')*64}
                if command=='patch':return {'patch':'d'*64} if args[0]=='diff' else {'checkpoint':'c'*64}
                if command=='put':return {'artifact':job.sha(pathlib.Path(args[0]))}
                if command=='evaluators':return {EVALUATOR:{'build':'e'*64,'backend':'test'}}
                raise AssertionError('Unexpected execution: '+command)
            with patch('weight_experiment.configure'),patch('weight_experiment.nc',side_effect=nc):
                # configure normally writes this artifact; keep its contract in the fixture.
                job.write(home/'llm-runtime.json',{})
                result=experiment(home,directory,session_dir,evaluate=False)
            self.assertIsNone(result['evaluation']);self.assertNotIn('evaluate',commands)
            self.assertEqual(job.read(session_dir/'spec.json')['dataset'],job.sha(directory/'heldout.json'))
            self.assertEqual(result['candidate'],'c'*64)

    def test_frozen_import_retry_never_calls_controller_or_selector(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp); (root/'input').mkdir(); (root/'search/selected').mkdir(parents=True)
            job.write(root/'state.json',{'status':'interrupted'})
            job.write(root/'request.json',{'request':{}}); job.write(root/'inputs.json',{})
            job.write(root/'search/selected/session.json',{'frozen':True})
            with patch('weight_agent.run') as agent, patch('select_weight_candidate.select') as selector, patch('weight_experiment.experiment',return_value={'candidate':'frozen','evaluation':None}) as importer:
                job.work(root,root,True)
            agent.assert_not_called(); selector.assert_not_called()
            importer.assert_called_once_with(root,root/'input',root/'search/selected',evaluate=False)
            self.assertEqual(job.read(root/'result.json')['candidate'],'frozen')

    def test_controller_budgets_are_forwarded_and_final_inference_is_not_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp); directory=root/'input'; directory.mkdir()
            for name in ['heldout','policy','selection']: job.write(directory/(name+'.json'),{'reserved':name})
            request={'backend':'codex','controller_model':'test-controller','max_rounds':9,'max_probes':3,'min_probes':2,'max_edit_elements':42,'timeout_seconds':60}
            job.write(root/'request.json',{'request':request});job.write(root/'state.json',{'status':'queued'})
            with patch.object(job,'prepare',return_value=directory), patch('weight_agent.run') as agent, patch('select_weight_candidate.select') as selector, patch('weight_experiment.experiment',return_value={'evaluation':None}) as importer:
                job.work(root,root,False)
            args=agent.call_args.args[0]
            self.assertEqual((args.max_rounds,args.max_probes,args.min_probes,args.max_edit_elements),(9,3,2,42))
            self.assertEqual(args.heldout_sha256,job.sha(directory/'heldout.json'))
            self.assertFalse(hasattr(args,'heldout'))
            selector.assert_called_once()
            self.assertFalse(importer.call_args.kwargs['evaluate'])

    def test_splits_reject_cross_split_and_previous_task_overlap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp); store = root/'store'; store.mkdir()
            old = root/'old'; job.write(old, {'samples':[{'text':'old example','label':0}]})
            digest = job.sha(old); old.rename(store/digest)
            for name,text in [('development','new dev'),('selection','new selection'),('heldout','new final')]:
                job.write(root/(name+'.json'), {'samples':[{'text':text,'label':0}]})
            job.validate_splits(root,store,{'development_sha256':digest})
            for text in ['old example','new dev']:
                job.write(root/'heldout.json',{'samples':[{'text':text,'label':0}]})
                with self.assertRaisesRegex(ValueError,'overlap'): job.validate_splits(root,store,{'development_sha256':digest})

    def test_resume_rejects_changed_snapshot_before_controller(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp); (root/'input').mkdir()
            job.write(root/'request.json', {'request':{}})
            job.write(root/'input/config.json', {'changed':True})
            job.write(root/'inputs.json', {'config.json':'0'*64})
            with patch('weight_agent.run') as agent:
                with self.assertRaisesRegex(ValueError,'snapshot'): job.work(root,root,True)
                agent.assert_not_called()


if __name__ == '__main__': unittest.main()
