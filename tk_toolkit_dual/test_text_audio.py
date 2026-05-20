import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

import tk_text_audio as text_audio


class TextAudioTests(unittest.TestCase):
    def test_direct_voice_id_is_applied(self):
        config = {'options': {'voice_id': 'default-voice'}}
        merged = text_audio.apply_text_audio_voice_options(
            'token',
            config,
            {'音色ID': 'direct-voice'},
        )
        self.assertEqual(merged['options']['voice_id'], 'direct-voice')

    def test_linked_voice_id_overrides_direct_voice_id(self):
        config = {'options': {'voice_id': 'default-voice'}}
        fields = {
            '音色ID': 'direct-voice',
            '选择音色': [{'record_ids': ['recv1']}],
        }
        with patch.object(text_audio, 'safe_get_record', return_value={'Voice ID': 'linked-voice', '生成状态': '成功'}):
            merged = text_audio.apply_text_audio_voice_options('token', config, fields)
        self.assertEqual(merged['options']['voice_id'], 'linked-voice')

    def test_linked_voice_requires_success_status(self):
        fields = {'选择音色': [{'record_ids': ['recv1']}]}
        with patch.object(text_audio, 'safe_get_record', return_value={'Voice ID': 'linked-voice', '生成状态': '生成中'}):
            with self.assertRaisesRegex(Exception, '音色生成状态不是成功'):
                text_audio.apply_text_audio_voice_options('token', {'options': {}}, fields)

    def test_audio_filename_uses_sanitized_copy_title(self):
        filename = text_audio.build_audio_filename('rec123', '  Hook: 50% off / Thai?  ', 'mp3')
        self.assertEqual(filename, 'Hook_50% off_Thai.mp3')


if __name__ == '__main__':
    unittest.main()
