import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from daily_ci.publish import publish, task_files

class PublishTests(unittest.TestCase):
    def test_ref_race_rebases_without_force_or_losing_other_files(self):
        calls=[]
        heads=iter(['first','second'])
        patches=0
        def api(method,path,body=None):
            nonlocal patches
            calls.append((method,path,body))
            if path=='/git/ref/heads/main': return {'object':{'sha':next(heads)}}
            if path.startswith('/git/commits/'): return {'tree':{'sha':path.rsplit('/',1)[1]+'-tree'}}
            if path=='/git/trees': return {'sha':'new-tree'}
            if path=='/git/commits': return {'sha':'new-commit'}
            if method=='PATCH':
                patches+=1
                if patches==1: raise HTTPError('https://api.github.com',422,'ref moved',{},None)
                return {}
        self.assertEqual(publish({'kanban/jobs/task.json':'{}'},api,'message',pause=lambda _:None),'new-commit')
        trees=[body for method,path,body in calls if path=='/git/trees']
        self.assertEqual([v['base_tree'] for v in trees],['first-tree','second-tree'])
        self.assertTrue(all(body['force'] is False for method,path,body in calls if method=='PATCH'))

    def test_blocked_publishes_only_current_status_and_rejects_unverified_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'kanban/jobs').mkdir(parents=True); (root/'kanban/data').mkdir()
            status=root/'kanban/jobs/daily-20261029-cann-123-1.json'
            status.write_text(json.dumps({'status':'BLOCKED'}))
            self.assertEqual(list(task_files(root,'cann','123','1')),['kanban/jobs/'+status.name])
            status.write_text(json.dumps({'status':'SUCCEEDED','result_id':'result'}))
            (root/'kanban/data/result.json').write_text(json.dumps({'id':'result','verification':{'artifact_identity':False}}))
            with self.assertRaisesRegex(ValueError,'not verified'): task_files(root,'cann','123','1')

if __name__=='__main__': unittest.main()
