import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import controller_models as models

class Catalog(unittest.TestCase):
    def test_codex_catalog_preserves_order_and_hides_internal_models(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'models_cache.json'
            path.write_text(json.dumps({'identity':{'private':'not returned'},'models':[
                {'slug':'gpt-test-b','display_name':'Test B','visibility':'list'},
                {'slug':'internal','visibility':'hide'}, {'slug':'--unsafe','visibility':'list'},
                {'slug':'gpt-test-a','visibility':'list'}]}))
            result=models.codex_models(path)
            self.assertEqual([m['id'] for m in result['models']],['gpt-test-b','gpt-test-a'])
            self.assertNotIn('private',json.dumps(result))
    def test_no_key_makes_no_network_request(self):
        with patch.object(models.urllib.request,'urlopen') as network:
            self.assertEqual(models.api_models(None)['models'],[])
            network.assert_not_called()
    def test_api_filters_nontext_and_never_echoes_credentials(self):
        response=MagicMock();response.__enter__.return_value=response
        response.read.return_value=json.dumps({'data':[{'id':'gpt-test'},{'id':'text-embedding-test'},{'id':'gpt-image-test'}]}).encode()
        with patch.object(models.urllib.request,'urlopen',return_value=response):
            result=models.api_models('test-secret')
        self.assertEqual(result['models'],[{'id':'gpt-test','name':'gpt-test'}])
        with patch.object(models,'api_models',side_effect=Exception('test-secret')):
            self.assertNotIn('test-secret',json.dumps(models.catalog('openai')))

if __name__=='__main__':unittest.main()
