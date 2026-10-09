"""Fixed chunks and supplied local vectors in a private persistent Chroma index.

This baseline embedding is lexical, not a pretrained semantic neural model.
No online collection, embedding download, environment credential, or cache.
"""
import hashlib
import math
import re
import unicodedata
from pathlib import Path
from .canonical import digest, text_hash
from .models import now, uid
from .retrieval_models import DocumentInput, KnowledgeDataset, ChunkConfig, KnowledgeIndex

DIMENSION = 1024

def normalize(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC',text)).strip().lower()

def embed(text):
    value = normalize(text)
    # Bigrams work for Chinese without a mutable tokenizer dictionary. English
    # words and character bigrams allow short queries to match longer passages.
    terms = re.findall(r'[a-z0-9]+',value)+[value[i:i+2] for i in range(len(value)-1) if not value[i:i+2].isspace()]
    vector = [0.] * DIMENSION
    for term in terms or [value]:
        bucket = int(hashlib.sha256(term.encode()).hexdigest()[:8],16) % DIMENSION
        vector[bucket] += 1.
    length = math.sqrt(sum(v*v for v in vector))
    return [v/length for v in vector] if length else vector

def embedding_snapshot():
    return {'provider':'local','model':'sha256-lexical-bigram-v1','dimension':DIMENSION,
            'normalization':'NFKC whitespace lowercase L2', 'distance_metric':'cosine',
            'model_version':'1','local_model_path':'experiments/retrieval_knowledge.py',
            'implementation_hash':text_hash(Path(__file__).read_text()),
            'configuration':{'hash':'sha256-first32bits','features':'english words + character bigrams'},
            'external_backend_revision':'NOT_APPLICABLE_LOCAL_DETERMINISTIC'}

def chunks_for(dataset, config):
    chunks = []
    for doc in sorted(dataset.documents,key=lambda d:d['document_id']):
        text = normalize(doc['text'])
        for index, start in enumerate(range(0,len(text),config.chunk_size-config.chunk_overlap)):
            chunk_text = text[start:start+config.chunk_size]
            content_hash = text_hash(chunk_text)
            chunks.append({'chunk_id':digest({'document_id':doc['document_id'],'chunk_index':index,'text_hash':content_hash}),
                           'document_id':doc['document_id'],'chunk_index':index,'text':chunk_text,'text_hash':content_hash,
                           'title':doc['title']})
            if start+config.chunk_size >= len(text): break
    return chunks

class FrozenKnowledge:
    def __init__(self, store):
        self.store=store
        # Physical isolation, not merely a filter on the online knowledge_base.
        self.path=store.root/'retrieval-chroma'

    def create(self, documents, name, dataset_id=None, metadata=None):
        if not 1<=len(documents)<=100: raise ValueError('Require 1..100 documents')
        documents=[DocumentInput.model_validate(d) for d in documents]
        if len({d.document_id for d in documents})!=len(documents): raise ValueError('Duplicate document ID')
        if sum(len(d.text) for d in documents)>2_000_000: raise ValueError('Dataset too large')
        if any(not normalize(d.text) for d in documents): raise ValueError('Empty document')
        with self.store.transaction():
            identifier=dataset_id or uid()
            # A supplied ID must name an existing dataset, not invent a revision.
            version=self.store.get('knowledge_datasets',identifier).version+1 if dataset_id else 1
            docs=[{**d.model_dump(),'content_hash':text_hash(d.text),'updated_at':now()} for d in documents]
            identity=[{k:d[k] for k in ('document_id','text','content_hash','metadata')} for d in sorted(docs,key=lambda d:d['document_id'])]
            obj=KnowledgeDataset(knowledge_dataset_id=identifier,version=version,name=name,
                                 documents=docs,knowledge_hash=digest(identity),metadata=metadata or {})
            return self.store.put('knowledge_datasets',obj)

    def client(self):
        import chromadb
        from chromadb.config import Settings
        return chromadb.PersistentClient(path=str(self.path),settings=Settings(anonymized_telemetry=False))

    def build(self, dataset_id, version, config=None):
        import chromadb
        dataset=self.store.get('knowledge_datasets',dataset_id,version)
        config=ChunkConfig.model_validate(config or {})
        chunks=chunks_for(dataset,config)
        chunk_hash=digest({'configuration':config.model_dump(),'chunks':chunks})
        embedding=embedding_snapshot()
        generation=digest({'dataset_id':dataset_id,'version':dataset.version,'knowledge_hash':dataset.knowledge_hash,
                           'chunks':chunk_hash,'embedding':embedding,'chroma_version':chromadb.__version__,
                           'configuration':{'hnsw':{'space':'cosine'}}})
        name='rag_'+generation
        with self.store.transaction():
            try:
                existing=self.store.get('knowledge_indices',generation)
            except FileNotFoundError: existing=None
            if existing:
                self.verify(existing)
                return existing
            client=self.client()
            # A half-built, unsealed collection after interruption has no authority.
            try: client.delete_collection(name)
            except Exception: pass
            collection=client.create_collection(name,embedding_function=None,configuration={'hnsw':{'space':'cosine'}})
            collection.add(ids=[c['chunk_id'] for c in chunks],documents=[c['text'] for c in chunks],
                           metadatas=[{'document_id':c['document_id'],'chunk_index':c['chunk_index'],'text_hash':c['text_hash']} for c in chunks],
                           embeddings=[embed(c['text']) for c in chunks])
            obj=KnowledgeIndex(index_id=generation,knowledge_dataset_id=dataset_id,knowledge_version=dataset.version,
                               knowledge_hash=dataset.knowledge_hash,chunk_config=config,chunks=chunks,chunk_snapshot_hash=chunk_hash,
                               embedding_snapshot={**embedding,'index_generation':generation,'chroma_version':chromadb.__version__},
                               index_configuration=collection.configuration,collection_name=name,index_generation=generation)
            self.verify(obj)
            return self.store.put('knowledge_indices',obj)

    def verify(self,index):
        import chromadb
        expected_embedding={**embedding_snapshot(),'index_generation':index.index_generation,'chroma_version':chromadb.__version__}
        if expected_embedding!=index.embedding_snapshot: raise ValueError('Embedding implementation changed; create a new Baseline/index')
        dataset=self.store.get('knowledge_datasets',index.knowledge_dataset_id,index.knowledge_version)
        if dataset.knowledge_hash!=index.knowledge_hash or chunks_for(dataset,index.chunk_config)!=index.chunks:
            raise ValueError('Frozen knowledge/chunk identity mismatch')
        if digest({'configuration':index.chunk_config.model_dump(),'chunks':index.chunks})!=index.chunk_snapshot_hash:
            raise ValueError('Chunk snapshot hash mismatch')
        try: collection=self.client().get_collection(index.collection_name,embedding_function=None)
        except Exception: raise ValueError('Frozen index unavailable') from None
        if collection.configuration!=index.index_configuration: raise ValueError('Frozen index configuration drift')
        if collection.configuration.get('hnsw',{}).get('space')!='cosine': raise ValueError('Index distance metric drift')
        actual=collection.get(include=['documents','metadatas','embeddings'])
        if len(actual['ids'])!=len(index.chunks) or set(actual['ids'])!={c['chunk_id'] for c in index.chunks}:
            raise ValueError('Frozen index membership drift')
        expected={c['chunk_id']:c for c in index.chunks}
        for i,identifier in enumerate(actual['ids']):
            c=expected[identifier]
            metadata={'document_id':c['document_id'],'chunk_index':c['chunk_index'],'text_hash':c['text_hash']}
            vector=actual['embeddings'][i]
            if (actual['documents'][i]!=c['text'] or actual['metadatas'][i]!=metadata or len(vector)!=DIMENSION
                or any(abs(float(a)-b)>1e-6 for a,b in zip(vector,embed(c['text'])))):
                raise ValueError('Frozen index content/vector drift')
        return collection

    def search(self,index,query,count):
        collection=self.client().get_collection(index.collection_name,embedding_function=None)
        raw=collection.query(query_embeddings=[embed(query)],n_results=min(count,len(index.chunks)),
                             include=['distances','documents','metadatas'])
        items=[{'chunk_id':identifier,'document_id':raw['metadatas'][0][i]['document_id'],
                'text':raw['documents'][0][i],'distance':float(raw['distances'][0][i]),
                'score':1-float(raw['distances'][0][i])} for i,identifier in enumerate(raw['ids'][0])]
        # Stable tie order; rank evidence records the actual deterministic policy.
        items.sort(key=lambda r:(r['distance'],r['chunk_id']))
        return [{**r,'rank':i+1} for i,r in enumerate(items)]
