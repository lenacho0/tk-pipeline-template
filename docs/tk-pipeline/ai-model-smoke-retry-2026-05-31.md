# AI 模型全量媒体 Smoke Test 结果

- 生成时间: 2026-05-31 09:46:02
- 模型数量: 3
- ok: 2
- failed: 1
- 说明: 报告已脱敏；不写业务记录，不触发 dispatcher。

## OTU / veo_3_1

- status: `ok`
- profile: `landscape_i2v`
- capability: `视频`
- endpoint: `https://otuapi.com/v1/videos`
- payload_keys: `aspect_ratio, model, prompt, seconds, size`
- size: `1280x720`
- aspect_ratio: `16:9`
- seconds: `8`
- reference_count: `1`
- response_status: `in_progress`
- task_id: `task_S9P8aO97LZP7GhanWWd1BddhCrBhmRO3`
- result_url: ``
- error_type: ``
- error: ``

## OTU / veo_3_1-hd

- status: `ok`
- profile: `landscape_i2v`
- capability: `视频`
- endpoint: `https://otuapi.com/v1/videos`
- payload_keys: `aspect_ratio, model, prompt, seconds, size`
- size: `1280x720`
- aspect_ratio: `16:9`
- seconds: `8`
- reference_count: `1`
- response_status: `in_progress`
- task_id: `task_EI2VJ5FXxVO5Zak7MGsAab70TT82xegm`
- result_url: ``
- error_type: ``
- error: ``

## AIHubMix / seeddance2.0

- status: `failed`
- profile: `vertical_i2v`
- capability: `视频`
- endpoint: `https://aihubmix.com/v1/videos`
- payload_keys: `aspect_ratio, model, prompt, seconds, size`
- size: `720x1280`
- aspect_ratio: `9:16`
- seconds: `8`
- reference_count: `1`
- response_status: ``
- task_id: ``
- result_url: ``
- error_type: `endpoint_error`
- error: `HTTP 500: {'error': {'message': 'no_valid_channel_error (tid: 2026053101460281782277174636336)', 'type': 'Aihubmix_api_error'}, 'type': 'error'}`
