#!/usr/bin/env python3
import json

SCHEMA_VERSION = 'pet_reference_v1'


def default_payload():
    return {
        'schema_version': SCHEMA_VERSION,
        'analysis_status': 'success',
        'meta': {
            'source_url': '',
            'normalized_url': '',
            'platform': 'Unknown',
            'analysis_model': 'gemini-3.1-pro-preview',
            'analyzed_at': '',
            'video_duration_sec': 0,
            'file_size_mb': 0,
        },
        'pet_anthro': {
            'is_pet_anthro': False,
            'confidence': 0,
            'pet_type': 'unknown',
            'narrative_subject': 'unknown',
            'anthro_intensity': 'unknown',
            'role_summary': '',
            'pet_anthro_mechanism': '',
        },
        'conversion': {
            'core_strategy': 'unknown',
            'hook_type': 'unknown',
            'visual_intensity': 'unknown',
            'sensitive_visual_types': ['none'],
            'product_integration_method': 'unknown',
            'cta_summary': '',
        },
        'content': {
            'summary': '',
            'opening_hook_analysis': '',
            'timeline_breakdown': [],
            'voiceover_structure': '',
            'rhythm_analysis': '',
            'selling_points_flow': '',
            'closed_loop_analysis': '',
        },
        'reuse': {
            'reusable_structure_template': '',
            'reusable_opening_template': '',
            'reusable_role_template': '',
            'reusable_cta_template': '',
            'fit_products': [],
            'unfit_products': [],
            'avoid_copying_notes': '',
        }
    }


def _merge(default_obj, value):
    if isinstance(default_obj, dict):
        src = value if isinstance(value, dict) else {}
        return {k: _merge(v, src.get(k)) for k, v in default_obj.items()}
    if isinstance(default_obj, list):
        return value if isinstance(value, list) else list(default_obj)
    return value if value is not None else default_obj


def normalize_payload(data):
    merged = _merge(default_payload(), data if isinstance(data, dict) else {})
    merged['schema_version'] = SCHEMA_VERSION
    return merged


def parse_and_normalize_json(text):
    data = json.loads(text)
    return normalize_payload(data)
