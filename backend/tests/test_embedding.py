import math
from unittest.mock import AsyncMock, patch

import pytest

from app.services.embedding import _l2_normalize, _make_batches, embed_texts


class TestEmbedding:
    def test_make_batches(self):
        items = list(range(10))
        batches = _make_batches(items, 3)
        assert batches == [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]

    def test_l2_normalize(self):
        vec = [3.0, 4.0]
        norm_vec = _l2_normalize(vec)
        assert norm_vec == [3.0 / 5.0, 4.0 / 5.0]

    def test_l2_normalize_zero(self):
        vec = [0.0, 0.0]
        assert _l2_normalize(vec) == [0.0, 0.0]

    def test_embed_texts_empty(self):
        assert embed_texts([]) == []

    @patch("app.services.embedding.create_embeddings", new_callable=AsyncMock)
    def test_embed_texts_batches_and_normalizes(self, mock_create):
        # mock create_embeddings to return different values for batches
        mock_create.side_effect = [
            [[3.0, 4.0], [0.0, 0.0]],  # batch 1
            [[1.0, 1.0]],  # batch 2
        ]
        texts = ["a", "b", "c"]

        with patch("app.services.embedding._BATCH_SIZE", 2):
            results = embed_texts(texts)

        assert len(results) == 3
        assert results[0] == [3.0 / 5.0, 4.0 / 5.0]
        assert results[1] == [0.0, 0.0]
        assert results[2] == [1.0 / math.sqrt(2), 1.0 / math.sqrt(2)]

        assert mock_create.call_count == 2
        mock_create.assert_any_call(["a", "b"])
        mock_create.assert_any_call(["c"])

    @patch("app.services.embedding.create_embeddings", new_callable=AsyncMock)
    def test_embed_texts_value_error_on_mismatched_length(self, mock_create):
        mock_create.return_value = [[1.0, 0.0]]  # returns 1 vector for 2 inputs
        with pytest.raises(ValueError, match="expected 2 vectors, got 1"):
            embed_texts(["a", "b"])
