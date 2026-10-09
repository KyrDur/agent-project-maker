"""Versioned local embeddings; no remote credentials and no lexical fallback.

The legacy module is byte-for-byte frozen to preserve existing snapshot hashes.
Semantic weights, tokenizer, backend and adapter are identified in each index.
"""
import hashlib
import inspect
from functools import lru_cache
from pathlib import Path
from threading import RLock
from . import retrieval_lexical_v1 as legacy
from .canonical import text_hash

SEMANTIC = 'all-MiniLM-L6-v2'
LEXICAL = 'sha256-lexical-bigram-v1'
_lock = RLock()
_state = None

class EmbeddingFailure(ValueError):
    pass

def _signature(folder):
    return tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                 for p in sorted(folder.iterdir()) if p.is_file())

@lru_cache(maxsize=8)
def _fingerprint(folder, signature):
    result = {}
    for name, _, _ in signature:
        h = hashlib.sha256()
        with (Path(folder)/name).open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                h.update(block)
        result[name] = h.hexdigest()
    return result

def semantic_state():
    global _state
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
    folder = ONNXMiniLM_L6_V2.DOWNLOAD_PATH / ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME
    with _lock:
        try:
            if _state is None or _state[0] != _signature(folder):
                ef = ONNXMiniLM_L6_V2(preferred_providers=['CPUExecutionProvider'])
                # Chroma validates the downloaded archive before extraction.
                ef(['model initialization'])
                signature = _signature(folder)
                hashes = _fingerprint(str(folder), signature)
                _state = (signature, ef, hashes)
            return _state[1:]
        except Exception as exc:
            raise EmbeddingFailure('EMBEDDING_MODEL_UNAVAILABLE') from exc

def snapshot(model=SEMANTIC):
    if model == LEXICAL:
        return legacy.embedding_snapshot()
    if model != SEMANTIC:
        raise ValueError('Unsupported embedding model')
    import chromadb
    import onnxruntime
    import tokenizers
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
    _, hashes = semantic_state()
    return {'provider':'local','model':SEMANTIC,'dimension':384,
            'normalization':'NFKC whitespace lowercase L2','distance_metric':'cosine',
            'model_version':'chroma-onnx-sha256','local_model_path':'Chroma local ONNX model cache',
            'implementation_hash':text_hash(Path(__file__).read_text()),
            'external_backend_revision':hashes['model.onnx'],
            'configuration':{'backend':'onnxruntime','execution_provider':'CPUExecutionProvider',
                'pooling':'attention-mask mean','max_input_tokens':256,
                'overflow_policy':'REJECT_NO_TRUNCATION','model_files_sha256':hashes,
                'backend_implementation_hash':text_hash(inspect.getsource(ONNXMiniLM_L6_V2)),
                'chromadb_version':chromadb.__version__,'onnxruntime_version':onnxruntime.__version__,
                'tokenizers_version':tokenizers.__version__}}

def encode(texts, model=SEMANTIC):
    if model == LEXICAL:
        return [legacy.embed(text) for text in texts]
    if model != SEMANTIC:
        raise ValueError('Unsupported embedding model')
    ef, _ = semantic_state()
    try:
        # The model's normal tokenizer truncates at 256. Check a separate,
        # untruncated tokenizer so the evidence never silently loses content.
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_str(ef.tokenizer.to_str())
        tokenizer.no_truncation()
        tokenizer.no_padding()
        if any(len(tokenizer.encode(text).ids) > 256 for text in texts):
            raise EmbeddingFailure('EMBEDDING_INPUT_TOO_LONG')
        vectors = ef(texts)
        result = [v.tolist() for v in vectors]
        import math
        if any(len(v)!=384 or any(not math.isfinite(x) for x in v) for v in result):
            raise EmbeddingFailure('EMBEDDING_MODEL_UNAVAILABLE')
        return result
    except EmbeddingFailure:
        raise
    except Exception as exc:
        raise EmbeddingFailure('EMBEDDING_MODEL_UNAVAILABLE') from exc

def model_for(index):
    model = index.embedding_snapshot.get('model')
    if model not in (SEMANTIC, LEXICAL):
        raise ValueError('Unsupported frozen embedding model')
    return model

def description(config):
    return ('本地语义模型 '+SEMANTIC if config.get('model') == SEMANTIC
            else '本地词汇向量 '+str(config.get('model', '未知')))
