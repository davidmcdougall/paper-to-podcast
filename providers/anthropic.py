"""Existing Anthropic transport; no calls until explicitly requested."""
import anthropic

ENDPOINT = 'https://api.anthropic.com'


def create_client(key, discovery=False):
    return anthropic.Anthropic(api_key=key, base_url=ENDPOINT,
        http_client=anthropic.DefaultHttpxClient(follow_redirects=False),
        timeout=8.0 if discovery else 120.0, max_retries=0)


class AnthropicText:
    input_unit = 'tokens'
    input_limit = 60_000
    prompt_character_limit = 180_000

    def __init__(self, client):
        self.client = client

    def count_tokens(self, **request):
        return self.client.messages.count_tokens(**request)

    def complete(self, **request):
        return self.client.messages.create(**request)

    def list_models(self):
        return [m.id for m in self.client.models.list(limit=100) if m.id.startswith('claude-')]

    def retrieve_model(self, model):
        return self.client.models.retrieve(model)
