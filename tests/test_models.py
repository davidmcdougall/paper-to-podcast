from types import SimpleNamespace as N
import pytest


class FakeClient:
    def __init__(self,items):self.items=items;self.calls=0;self.models=self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def list(self,**kw):
        self.calls+=1
        return iter(self.items)
    def retrieve(self,model):return N(id=model)


def test_family_names(appmod):
    for model,family in [('claude-3-5-sonnet-20241022','sonnet'),('claude-sonnet-5','sonnet'),('claude-haiku-4-5-20251001','haiku')]:
        assert appmod._family(model)==family


def test_cache_and_successful_empty(appmod,monkeypatch):
    client=FakeClient([N(id='claude-sonnet-5')])
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:client)
    assert appmod.available_models()==['claude-sonnet-5']
    assert appmod.available_models()==['claude-sonnet-5']
    assert client.calls==1
    appmod._MODEL_CACHE['until']=0;client.items=[]
    assert appmod.available_models()==[]


def test_no_cross_family_fallback(appmod,monkeypatch):
    client=FakeClient([N(id='claude-opus-5-5')])
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:client)
    with pytest.raises(appmod.UserError):appmod._newest_in_family('sonnet')


def test_discovery_failure_discards_stale(appmod,monkeypatch):
    appmod._MODEL_CACHE.update(ids=['claude-retired'],until=0)
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:(_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(appmod.UserError):appmod.available_models()
    assert appmod._MODEL_CACHE['ids']==[]


def test_page_load_does_not_discover(appmod,client,monkeypatch):
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:pytest.fail('network on page load'))
    assert client.get('/').status_code==200


def test_reject_truncated_output(appmod,monkeypatch):
    client=FakeClient([])
    client.messages=N(count_tokens=lambda **kw:N(input_tokens=1),create=lambda **kw:N(
        content=[N(type='text',text='cut off')],stop_reason='max_tokens',usage=N(input_tokens=1,output_tokens=1)))
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:client)
    with pytest.raises(appmod.UserError):appmod.complete_message('model','paper',100,[])


def test_prompt_character_limit(appmod,monkeypatch):
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:pytest.fail('oversized call'))
    with pytest.raises(appmod.UserError):appmod.complete_message('model','x'*1_000_000,100,[])


def test_override_validation_failure(appmod,monkeypatch):
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:(_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(appmod.UserError):appmod.resolve_models({})


def test_voice_pass_failure_retains_first_draft(appmod,monkeypatch):
    calls=[]
    def complete(*args):
        calls.append(1)
        if len(calls)==2:raise RuntimeError('offline')
        return 'Complete first-pass script'
    monkeypatch.setattr(appmod,'complete_message',complete)
    warnings=[]
    result=appmod.generate_podcast_script('source',model='writing',fast='fast',warnings=warnings)
    assert result=='Complete first-pass script'
    assert 'Voice editing failed' in warnings[0]


def test_actual_sdk_follows_model_pages(appmod,monkeypatch):
    import httpx2
    import anthropic
    calls=[]
    def handle(request):
        calls.append(str(request.url))
        second='after_id=' in str(request.url)
        mid='claude-haiku-4-5-20251001' if second else 'claude-sonnet-5'
        return httpx2.Response(200,json={'data':[{'id':mid,'type':'model','display_name':mid,
            'created_at':'2026-01-01T00:00:00Z'}], 'has_more':not second,'first_id':mid,'last_id':mid})
    client=anthropic.Anthropic(api_key='test',http_client=httpx2.Client(transport=httpx2.MockTransport(handle)))
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:client)
    assert appmod.available_models()==['claude-sonnet-5','claude-haiku-4-5-20251001']
    assert len(calls)==2


def test_input_token_budget_counts_before_generation(appmod,monkeypatch):
    client=FakeClient([])
    client.messages=N(count_tokens=lambda **kw:N(input_tokens=60000),
                      create=lambda **kw:pytest.fail('oversized generation'))
    monkeypatch.setattr(appmod,'claude_client',lambda **kw:client)
    with pytest.raises(appmod.UserError):appmod.complete_message('model','paper',100,[])
