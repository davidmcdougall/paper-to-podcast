import pytest
import urllib.request


@pytest.mark.parametrize('value,expected',[
    ('1706.03762v2','1706.03762v2'),
    ('https://arxiv.org/pdf/1706.03762v2.pdf','1706.03762v2'),
    ('hep-th/9901001v3','hep-th/9901001v3'),
])
def test_preserve_version(appmod,value,expected):
    assert appmod.parse_arxiv_id(value)==expected


@pytest.mark.parametrize('value',[
    'https://127.0.0.1/secret','https://arxiv.org.evil.example/abs/1706.03762',
    '1706.03762&max_results=1000','https://arxiv.org/abs/1706.03762?x=1',
    'https://user@arxiv.org/abs/1706.03762','../../secret',
])
def test_reject_invalid_id(appmod,value):
    with pytest.raises(appmod.UserError):appmod.parse_arxiv_id(value)


@pytest.mark.parametrize('url',['http://arxiv.org/pdf/1706.03762','https://evil.example/x','https://127.0.0.1/x'])
def test_reject_redirect_escape(appmod,url):
    handler=appmod.ArxivRedirect()
    with pytest.raises(appmod.UserError):
        handler.redirect_request(urllib.request.Request('https://arxiv.org/x'),None,302,'',{},url)
