import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tk_voice_library as voices


class VoiceLibraryTests(unittest.TestCase):
    def test_build_minimax_endpoint_maps_user_v1_base(self):
        self.assertEqual(
            voices.build_minimax_endpoint('https://api.aitgenne.com/v1', 'voice_design'),
            'https://api.aitgenne.com/minimax/v1/voice_design',
        )
        self.assertEqual(
            voices.build_minimax_endpoint('https://api.aitgenne.com/minimax/v1', 'files/upload'),
            'https://api.aitgenne.com/minimax/v1/files/upload',
        )

    def test_generate_clone_voice_id_is_valid_and_stable_shape(self):
        voice_id = voices.generate_clone_voice_id('recabc123XYZ')
        self.assertTrue(voice_id.startswith('tkvoice_recabc123XYZ_'))
        self.assertRegex(voice_id, r'^[A-Za-z][A-Za-z0-9_-]{7,255}$')

    def test_build_reference_audio_path_preserves_supported_extension(self):
        path = voices.build_reference_audio_path('/tmp/task', 'recabc', [{'name': 'A2.WAV', 'file_token': 'token'}])
        self.assertEqual(path, '/tmp/task/recabc_reference_audio.wav')

    def test_parse_voice_design_response(self):
        fake_audio = b'\xff\xfb' + b'a' * 1200
        voice_id, audio = voices.parse_voice_design_response({
            'voice_id': 'ttv-voice-1',
            'trial_audio': fake_audio.hex(),
            'base_resp': {'status_code': 0, 'status_msg': 'success'},
        })
        self.assertEqual(voice_id, 'ttv-voice-1')
        self.assertEqual(audio, fake_audio)

    def test_upload_clone_audio_returns_file_id(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            'file': {'file_id': 1234567890},
            'base_resp': {'status_code': 0, 'status_msg': 'success'},
        }
        with patch.object(voices.requests, 'post', return_value=response), patch('builtins.open', unittest.mock.mock_open(read_data=b'audio')):
            file_id = voices.upload_clone_audio('/tmp/ref.mp3', {'api_key': 'key', 'api_base': 'https://api.aitgenne.com/v1'})
        self.assertEqual(file_id, 1234567890)

    def test_upload_clone_audio_reports_non_json_response_context(self):
        response = Mock()
        response.status_code = 502
        response.headers = {'content-type': 'text/html'}
        response.text = '<html>Bad Gateway</html>'
        response.json.side_effect = ValueError('Expecting value: line 1 column 1 (char 0)')
        with patch.object(voices.requests, 'post', return_value=response), patch('builtins.open', unittest.mock.mock_open(read_data=b'audio')):
            with self.assertRaisesRegex(Exception, 'MiniMax upload returned non-JSON HTTP 502'):
                voices.upload_clone_audio('/tmp/ref.mp3', {'api_key': 'key', 'api_base': 'https://api.aitgenne.com/v1'})

    def test_upload_clone_audio_falls_back_to_proxy_files_endpoint(self):
        html_response = Mock()
        html_response.status_code = 200
        html_response.headers = {'content-type': 'text/html'}
        html_response.text = '<html>Proxy landing page</html>'
        html_response.json.side_effect = ValueError('Expecting value: line 1 column 1 (char 0)')

        json_response = Mock()
        json_response.status_code = 200
        json_response.headers = {'content-type': 'application/json'}
        json_response.json.return_value = {
            'file': {'file_id': 399776975950360},
            'base_resp': {'status_code': 0, 'status_msg': 'success'},
        }

        with patch.object(voices.requests, 'post', side_effect=[html_response, json_response]) as post, patch('builtins.open', unittest.mock.mock_open(read_data=b'audio')):
            file_id = voices.upload_clone_audio('/tmp/ref.mp3', {'api_key': 'key', 'api_base': 'https://api.aitgenne.com/v1'})

        self.assertEqual(file_id, 399776975950360)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[1].args[0], 'https://api.aitgenne.com/minimax/v1/files')

    def test_clone_voice_posts_file_id_and_custom_voice_id(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            'demo_audio': 'https://example.com/demo.mp3',
            'base_resp': {'status_code': 0, 'status_msg': 'success'},
        }
        with patch.object(voices.requests, 'post', return_value=response) as post:
            demo = voices.clone_voice(123, 'tkvoice_record_1', 'preview', {'api_key': 'key', 'api_base': 'https://api.aitgenne.com/v1', 'model': 'speech-2.8-turbo', 'options': {'language_boost': 'Thai'}})
        self.assertEqual(demo, 'https://example.com/demo.mp3')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['file_id'], 123)
        self.assertEqual(payload['voice_id'], 'tkvoice_record_1')
        self.assertEqual(payload['language_boost'], 'Thai')

    def test_clone_voice_reports_non_json_response_context(self):
        response = Mock()
        response.status_code = 404
        response.headers = {'content-type': 'text/plain'}
        response.text = 'not found'
        response.json.side_effect = ValueError('Expecting value: line 1 column 1 (char 0)')
        with patch.object(voices.requests, 'post', return_value=response):
            with self.assertRaisesRegex(Exception, 'MiniMax clone returned non-JSON HTTP 404'):
                voices.clone_voice(123, 'tkvoice_record_1', 'preview', {'api_key': 'key', 'api_base': 'https://api.aitgenne.com/v1'})


if __name__ == '__main__':
    unittest.main()
