# app/core/tokenizer.py

import tiktoken

ENCODING_NAME = "cl100k_base"
encoder = tiktoken.get_encoding(ENCODING_NAME)