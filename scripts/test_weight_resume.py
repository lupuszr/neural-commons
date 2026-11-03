import copy
import json
import unittest
from weight_agent import controller_history, restore_transcript


def entry(tool, arguments, result):
    return {'action':{'tool':tool,'arguments':json.dumps(arguments)},'result':result}


class Resume(unittest.TestCase):
    def setUp(self):
        self.commitment={'target_sha256':'same-model','max_probes':20,'controller':'same-controller',
                         'implementation_sha256':{'code':'old'}}
        self.initial={'commitment':self.commitment,'initial':{'baseline':{'accuracy':0.7}}}
        self.actions=[entry('inspect',{'tensor':'w'},{}),
                      entry('inspect_diff',{'tensor':'w','start':0,'count':1},{'changes':[{'index':0}]}),
                      entry('contrast',{'positive_label':0,'negative_label':1},
                            {'source_tensor':'activation_contrast.0.1','values':[0.5,-0.5]}),
                      entry('experiment',{'hypothesis':'next edit','operations':[]},
                            {'candidate':0,'accuracy':0.8,'predictions':[]})]
        self.rows=[self.initial,{'round':0,'decision':{'actions':[a['action'] for a in self.actions]}},*self.actions]

    def test_resume_restores_evidence_and_attempt_count_without_repeating_probes(self):
        updated={**self.commitment,'implementation_sha256':{'code':'new'}}
        restored=restore_transcript(self.rows,updated)
        original,history,candidates,inspected,features,probes,selected,diff_read,last,pending=restored
        self.assertEqual(original,self.commitment)
        self.assertEqual(history[1:],self.actions)
        self.assertEqual(probes,1);self.assertEqual(candidates[0]['id'],0)
        self.assertEqual(inspected,{'w'});self.assertTrue(diff_read)
        self.assertEqual(features['activation_contrast.0.1'].tolist(),[0.5,-0.5])
        self.assertEqual((last,pending),(0,[]));self.assertIsNone(selected)
        with self.assertRaisesRegex(ValueError,'commitment mismatch'):
            restore_transcript(self.rows,{**updated,'max_probes':21})
        with self.assertRaisesRegex(ValueError,'commitment mismatch'):
            restore_transcript(self.rows,{**updated,'target_sha256':'different'})

    def test_resume_keeps_unexecuted_actions_and_rejects_unrecorded_actions(self):
        restored=restore_transcript(self.rows[:-1],self.commitment)
        self.assertEqual(restored[-1],[self.actions[-1]['action']]);self.assertEqual(restored[5],0)
        bad=copy.deepcopy(self.rows);bad[-1]['action']={**bad[-1]['action'],'tool':'finish'}
        with self.assertRaises(ValueError):restore_transcript(bad,self.commitment)

    def test_context_compaction_preserves_full_audit_and_recent_observations(self):
        rows=[{'initial':{'baseline':{'predictions':[{'text':'development'}]}}}]
        for i in range(4):
            rows.append(entry('experiment',{'hypothesis':str(i),'operations':[]},
                              {'candidate':i,'accuracy':0.5,'predictions':[
                                  {'text':'development','label':0,'prediction':1,'nll':2.}]}))
        before=copy.deepcopy(rows);compacted=controller_history(rows)
        self.assertEqual(rows,before)
        self.assertNotIn('predictions',compacted[1]['result'])
        self.assertEqual(compacted[1]['result']['confusion'],{'0->1':1})
        self.assertIn('predictions',compacted[-1]['result'])
        self.assertEqual(compacted[0],rows[0])

if __name__=='__main__':unittest.main()
