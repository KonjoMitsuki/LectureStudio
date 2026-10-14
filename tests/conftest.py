import pytest

@pytest.fixture
def valid_lecture():
    return {'title': '探索', 'learning_goals': ['手順を理解する'], 'warnings': [], 'scenes': [{
        'id': 'scene_001', 'title': '線形探索', 'narration': '先頭から順番に値を比較します。',
        'concepts': ['探索'], 'source_pages': [1], 'supplemental': False, 'estimated_seconds': 5,
        'visual': {'type': 'flowchart', 'nodes': [{'id': 'a', 'label': '開始'}, {'id': 'b', 'label': '比較'}],
            'edges': [{'id': 'a-b', 'source': 'a', 'target': 'b', 'label': ''}], 'items': [], 'columns': [],
            'rows': [], 'formula': '', 'steps': [{'action': 'highlight_node', 'target': 'a'}]}
    }]}
