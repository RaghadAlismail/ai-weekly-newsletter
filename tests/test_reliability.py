import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import Mock,patch
import sqlite3
import requests
from ai_request import post_completion
from generation_quality import validate_copy
from source_fetch import fetch_article

def good():return {'title_ar':'شركة تطلق أداة جديدة','body_ar':' '.join(['كلمة']*90),'title_en':'Company launches tool','body_en':'Source text','approved':True}
def response(status,error=None,headers=None):
 r=Mock(ok=status==200,status_code=status,headers=headers or {})
 r.json.return_value={'error':error or {}}
 return r
class ReliabilityTests(unittest.TestCase):
 def test_rate_limit_recovers_and_honors_retry_after(self):
  with patch('ai_request.requests.post',side_effect=[response(429,headers={'Retry-After':'12'}),response(200)]) as post,patch('ai_request.time.sleep') as sleep:
   self.assertTrue(post_completion('x',headers={},json={}).ok)
   self.assertEqual(post.call_count,2);self.assertGreaterEqual(sleep.call_args.args[0],12)
 def test_quota_not_retried(self):
  with patch('ai_request.requests.post',return_value=response(429,{'code':'insufficient_quota'})) as post,patch('ai_request.time.sleep') as sleep:
   with self.assertRaisesRegex(ValueError,'credits'):post_completion('x',headers={},json={})
   post.assert_called_once();sleep.assert_not_called()
 def test_persistent_rate_limit_bounded(self):
  with patch('ai_request.requests.post',return_value=response(429)) as post,patch('ai_request.time.sleep') as sleep:
   with self.assertRaisesRegex(ValueError,'rate limit'):post_completion('x',headers={},json={})
   self.assertEqual(post.call_count,4);self.assertEqual(sleep.call_count,3)
 def test_long_retry_after_does_not_retry_early(self):
  with patch('ai_request.requests.post',return_value=response(429,headers={'Retry-After':'180'})) as post,patch('ai_request.time.sleep') as sleep:
   with self.assertRaises(ValueError):post_completion('x',headers={},json={})
   post.assert_called_once();sleep.assert_not_called()
 def test_corrections_are_fact_checked_again(self):
  corrected={**good(),'approved':False}
  review=Mock(return_value=good());fact=Mock(side_effect=[corrected,good()])
  self.assertTrue(validate_copy(good(),'Companies','title','source',review,fact)['approved']);self.assertEqual(fact.call_count,2)
 def test_factual_failure_stays_blocked(self):
  with self.assertRaisesRegex(ValueError,'Source-fidelity'):
   validate_copy(good(),'Companies','title','source',Mock(return_value=good()),Mock(return_value={**good(),'approved':False}))
 def test_invalid_title_repaired_then_verified(self):
  bad={**good(),'title_ar':'OpenAI'}
  review=Mock(side_effect=[bad,good()]);fact=Mock(side_effect=[bad,good()])
  self.assertEqual(validate_copy(bad,'Companies','title','source',review,fact)['title_ar'],good()['title_ar'])
 def test_no_approval_cannot_pass(self):
  result=good();result.pop('approved')
  with self.assertRaises(ValueError):validate_copy(result,'Companies','title','source',Mock(return_value=result),Mock(return_value=result))
 def test_source_403_has_manual_fallback(self):
  r=response(403)
  with patch('source_fetch.fetch_bytes',side_effect=requests.HTTPError(response=r)):
   with self.assertRaisesRegex(ValueError,'Paste the original'):fetch_article('https://example.com')
 def test_edited_article_invalidates_cached_revision(self):
  c=sqlite3.connect(':memory:');c.executescript('CREATE TABLE validated_article_generations(article_id INTEGER PRIMARY KEY,revision INTEGER); CREATE TABLE article_media(article_id INTEGER); INSERT INTO validated_article_generations VALUES(1,2); INSERT INTO article_media VALUES(1);')
  sql='SELECT v.article_id FROM validated_article_generations v JOIN article_media m ON m.article_id=v.article_id WHERE v.article_id=? AND v.revision=?'
  self.assertIsNotNone(c.execute(sql,(1,2)).fetchone());self.assertIsNone(c.execute(sql,(1,3)).fetchone())
if __name__=='__main__':unittest.main()
