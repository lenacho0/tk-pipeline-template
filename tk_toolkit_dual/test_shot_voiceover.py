import json
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tk_shot_voiceover as voiceover


class ShotVoiceoverTests(unittest.TestCase):
    def test_build_t2a_url_accepts_user_v1_base(self):
        self.assertEqual(
            voiceover.build_t2a_url('https://api.aitgenne.com/v1'),
            'https://api.aitgenne.com/minimax/v1/t2a_v2',
        )

    def test_build_t2a_url_accepts_documented_base(self):
        self.assertEqual(
            voiceover.build_t2a_url('https://api.aitgenne.com/minimax/v1/t2a_v2'),
            'https://api.aitgenne.com/minimax/v1/t2a_v2',
        )

    def test_normalize_audio_length_milliseconds(self):
        self.assertEqual(voiceover.normalize_audio_length_seconds(9900), 9.9)
        self.assertEqual(voiceover.normalize_audio_length_seconds(828), 0.828)
        self.assertEqual(voiceover.normalize_audio_length_seconds(9.5), 9.5)

    def test_build_payload_uses_prompt_options(self):
        config = {
            'model': 'speech-2.8-turbo',
            'options': json.loads('{"voice_id":"voice-x","speed":1.05,"language_boost":"Thai"}'),
        }
        payload = voiceover.build_minimax_payload('สวัสดี', config)
        self.assertEqual(payload['model'], 'speech-2.8-turbo')
        self.assertEqual(payload['voice_setting']['voice_id'], 'voice-x')
        self.assertEqual(payload['voice_setting']['speed'], 1.05)
        self.assertEqual(payload['language_boost'], 'Thai')
        self.assertEqual(payload['audio_setting']['format'], 'mp3')

    def test_build_payload_uses_raw_model_from_display_name(self):
        payload = voiceover.build_minimax_payload('สวัสดี', {
            'model': 'Aitgenne / speech-2.8-hd',
            'options': {'voice_id': 'voice-x'},
        })
        self.assertEqual(payload['model'], 'speech-2.8-hd')

    def test_record_voice_id_overrides_default_config_voice_id(self):
        config = {'model': 'speech-2.8-turbo', 'options': {'voice_id': 'default-voice', 'speed': 1.0}}
        merged = voiceover.apply_record_voice_options(config, {'口播音色ID': 'record-voice'})
        payload = voiceover.build_minimax_payload('hello', merged)
        self.assertEqual(payload['voice_setting']['voice_id'], 'record-voice')
        self.assertEqual(payload['voice_setting']['speed'], 1.0)

    def test_synthesize_decodes_hex_audio(self):
        fake_audio = b'\xff\xfb' + b'a' * 1200
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            'data': {'audio': fake_audio.hex(), 'status': 2},
            'extra_info': {'audio_length': 1234, 'audio_format': 'mp3'},
            'base_resp': {'status_code': 0, 'status_msg': 'success'},
        }
        with patch.object(voiceover.requests, 'post', return_value=response) as post:
            result = voiceover.synthesize_voiceover(
                'hello',
                {'api_key': 'test-key', 'api_base': 'https://api.aitgenne.com/v1', 'model': 'speech-2.8-turbo', 'options': {'voice_id': 'voice-x'}},
            )
        self.assertEqual(result['audio_bytes'], fake_audio)
        self.assertEqual(result['duration_sec'], 1.234)
        called_url = post.call_args.args[0]
        self.assertEqual(called_url, 'https://api.aitgenne.com/minimax/v1/t2a_v2')


if __name__ == '__main__':
    unittest.main()
