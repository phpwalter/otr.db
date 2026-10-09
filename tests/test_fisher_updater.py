"""Offline regression tests against existing updater. Run with unittest discover."""
import importlib.util
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

UPDATER=Path(__file__).resolve().parents[1]/'scripts'/'update_fisher_by_episode.py'
spec=importlib.util.spec_from_file_location('fisher_updater',UPDATER)
updater=importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

class FisherTests(unittest.TestCase):
    def test_title_is_ignored(self):
        n, updates=updater.normalized_record({'episode_number':'0063','episode_title':'Completely different title','fisher_rubric':'87.5 / 100'},1)
        self.assertEqual(n,'63')
        self.assertEqual(updates,{'fisher_rubric':Decimal('87.5')})
    def test_cast_only(self):
        _,updates=updater.normalized_record({'episode_number':540,'cast_roles':'Jane Doe as Voice'},1)
        self.assertEqual(updates['fisher_cast_roles'],'Jane Doe as Voice')
    def test_reject_bad_rating(self):
        with self.assertRaises(ValueError):
            updater.normalized_record({'episode_number':1,'fisher_rubric':'101'},1)
    def test_reject_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'sample.csv'
            p.write_text('episode_number,fisher_rubric\n001,70\n1,80\n',encoding='utf-8')
            with self.assertRaises(ValueError):
                updater.read_records(p)
    def test_placeholder_password_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'.env'
            p.write_text('DB_PASSWORD=REPLACE_WITH_LOCAL_PASSWORD\n',encoding='utf-8')
            with self.assertRaises(ValueError):
                updater.get_dsn(env_path=p)

if __name__=='__main__': unittest.main()
