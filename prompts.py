"""Literal prompt templates and immutable history; no providers or executable templates."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from filelock import FileLock, Timeout
import storage

REQUIRED = {
    'script': frozenset({'length_rule', 'notes', 'source'}),
    'voice_edit': frozenset({'script'}),
    'summary': frozenset({'title', 'source'}),
    'show_notes': frozenset({'title', 'authors', 'source'}),
    'metadata': frozenset({'source'}),
}
SAMPLING_VERSIONS = {
    'script': 'head-middle-tail-word-character-token-v1',
    'voice_edit': 'none-v1', 'summary': 'head-middle-tail-8000-words-v1',
    'show_notes': 'head-middle-tail-6000-words-v1', 'metadata': 'first-3000-words-v1',
}
MAX_TEMPLATE_BYTES = 32_000
SAMPLE = MappingProxyType(dict(length_rule='500–2500 words, as the substance warrants; never pad to fill time',
    notes='Listener notes', source='Bundled research sample.', script='A spoken draft.',
    title='Sample paper', authors='Jane Smith, John Doe'))


class PromptError(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate(name, raw):
    if name not in REQUIRED:
        raise PromptError('Unknown prompt name.')
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_TEMPLATE_BYTES:
        raise PromptError('Prompt must contain 1–32,000 UTF-8 bytes.')
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        raise PromptError('Prompt must be UTF-8.') from None
    if '\x00' in text:
        raise PromptError('Prompt cannot contain NUL characters.')
    if 'source' in REQUIRED[name]:
        text = text.rstrip()  # Editor final newlines do not move source into the instructions.
    fields = re.findall(r'\{([^{}]*)\}', text)
    remaining = re.sub(r'\{[^{}]*\}', '', text)
    if '{' in remaining or '}' in remaining or set(fields) != REQUIRED[name]:
        raise PromptError('Use exactly the documented literal placeholders for this prompt; no formatting or expressions.')
    if 'source' in REQUIRED[name] and (fields.count('source') != 1 or not text.endswith('{source}')):
        raise PromptError('{source} must appear exactly once, at the end of the template.')
    return text


@dataclass(frozen=True)
class Template:
    name: str
    raw: bytes
    sha256: str
    warning: str = ''
    error: str = ''

    def render(self, **values):
        if self.error:
            raise PromptError(self.error)
        if set(values) != REQUIRED[self.name] or any(not isinstance(v, str) for v in values.values()):
            raise PromptError('Missing or invalid prompt inputs.')
        # One pass: braces in user/source text are literal and never evaluated.
        return re.sub(r'\{([^{}]*)\}', lambda match: values[match[1]], validate(self.name, self.raw))

    def prefix(self, **values):
        if 'source' not in REQUIRED[self.name]:
            raise PromptError('This prompt has no source suffix.')
        return self.render(source='', **values)


class PromptStore:
    def __init__(self, data_dir, shipped_dir=None):
        self.root = Path(data_dir) / 'prompts'
        self.shipped = Path(shipped_dir) if shipped_dir else Path(__file__).resolve().parent / 'prompt_templates'
        self.history_root = self.root / 'history'

    def _default(self, name):
        if name not in REQUIRED:
            raise PromptError('Unknown prompt name.')
        raw = (self.shipped / (name + '.md')).read_bytes()
        validate(name, raw)
        return raw

    def _archive(self, name, raw):
        sha = digest(raw)
        path = self.history_root / name / (sha + '.md')
        if path.exists():
            if path.read_bytes() != raw:
                raise PromptError('Prompt history is corrupt; original preserved for repair.')
        else:
            storage.atomic_write(path, raw)
        return sha

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            with FileLock(str(self.root / '.lock'), timeout=10):
                yield
        except Timeout:
            raise PromptError('Prompt storage is busy; wait for the prompt edit or snapshot to finish and retry.') from None

    def _write_seed(self, state):
        storage.atomic_write(self.root / '.seeded', json.dumps(state, sort_keys=True).encode('utf-8'))

    def _seed(self):
        marker = self.root / '.seeded'
        if marker.exists():
            raw = marker.read_bytes()
            if raw != b'1\n':
                try:
                    state = json.loads(raw)
                    valid = (isinstance(state, dict) and set(state) == {'schema_version', 'defaults'}
                             and type(state['schema_version']) is int and state['schema_version'] == 1
                             and isinstance(state['defaults'], dict) and set(state['defaults']) == set(REQUIRED)
                             and all(value is None or isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)
                                     for value in state['defaults'].values()))
                except (ValueError, UnicodeError):
                    valid = False
                if not valid:
                    raise PromptError('Prompt seed marker is corrupt or unsupported; original preserved.')
                return state
            # Old marker has no baseline hashes. Adopt only byte-identical current
            # defaults; preserve every ambiguous older/custom copy.
            defaults = {}
            for name in REQUIRED:
                path = self.root / (name + '.md')
                default = self._default(name)
                defaults[name] = digest(default) if path.exists() and path.read_bytes() == default else None
            state = {'schema_version': 1, 'defaults': defaults}
            self._write_seed(state)
            return state
        defaults = {}
        for name in REQUIRED:
            path = self.root / (name + '.md')
            default = self._default(name)
            if not path.exists():
                storage.atomic_write(path, default)
            defaults[name] = digest(default) if path.read_bytes() == default else None
        state = {'schema_version': 1, 'defaults': defaults}
        self._write_seed(state)
        return state

    def snapshot(self):
        with self._locked():
            state = self._seed()
            result = {}
            for name in REQUIRED:
                warning = ''
                reason = ''
                try:
                    with (self.root / (name + '.md')).open('rb') as stream:
                        raw = stream.read(MAX_TEMPLATE_BYTES + 1)
                    validate(name, raw)
                except FileNotFoundError:
                    reason = 'Editable file is missing.'
                except OSError:
                    reason = 'Editable file cannot be read.'
                except PromptError as exc:
                    reason = str(exc)
                default = self._default(name)
                if reason:
                    raw = default
                    warning = f'{name} prompt missing or invalid: {reason} Shipped default used; repair or reset the editable prompt.'
                error = ''
                try:
                    sha = digest(raw)
                    if not reason and sha == state['defaults'][name] and raw != default:
                        # Archive both versions before replacing an untouched copy.
                        self._archive(name, raw)
                        self._archive(name, default)
                        storage.atomic_write(self.root / (name + '.md'), default)
                        raw = default
                    self._archive(name, raw)
                    if not reason and raw == default and state['defaults'][name] != digest(default):
                        state['defaults'][name] = digest(default)
                        self._write_seed(state)
                except PromptError as exc:
                    # A corrupt version blocks only this template's reuse. Other
                    # templates and non-text operations remain usable.
                    error = f'{name} prompt unavailable: {exc}'
                result[name] = Template(name, raw, digest(raw), warning, error)
            return MappingProxyType(result)

    def save(self, name, text):
        raw = text.encode('utf-8')
        validate(name, raw)
        with self._locked():
            state = self._seed()
            path = self.root / (name + '.md')
            if path.exists():
                previous = path.read_bytes()
                # Preserve even an externally invalid version for repair.
                self._archive(name, previous)
            sha = self._archive(name, raw)
            storage.atomic_write(path, raw)
            if raw == self._default(name):
                state['defaults'][name] = sha
                self._write_seed(state)
        return sha

    def reset(self, name):
        return self.save(name, self._default(name).decode('utf-8'))

    def history(self, name):
        self._default(name)  # Validate name before constructing a path.
        folder = self.history_root / name
        return sorted(p.stem for p in folder.glob('*.md') if re.fullmatch(r'[0-9a-f]{64}', p.stem))

    def historical(self, name, sha):
        self._default(name)
        if not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise PromptError('Invalid prompt history hash.')
        try:
            raw = (self.history_root / name / (sha + '.md')).read_bytes()
        except FileNotFoundError:
            raise PromptError('Prompt history version was not found.') from None
        if digest(raw) != sha:
            raise PromptError('Prompt history is corrupt; original preserved for repair.')
        return raw

    def preview(self, name, text=None):
        if text is None:
            template = self.snapshot()[name]
        else:
            raw = text.encode('utf-8'); validate(name, raw)
            template = Template(name, raw, digest(raw))
        rendered = template.render(**{k: SAMPLE[k] for k in REQUIRED[name]})
        return {'text': rendered, 'estimated_tokens': (len(rendered) + 3) // 4,
                'estimate_label': 'Rough character-based estimate; not provider token counting.',
                'warning': template.warning}


def input_reference(text, reference=None):
    raw = text.encode('utf-8')
    result = {'sha256': digest(raw), 'bytes': len(raw)}
    if reference is not None:
        result['reference'] = reference
    return result


class AttemptJournal:
    """Write intent before network access; interruptions leave status=started, never success."""
    def __init__(self, data_dir):
        self.root = Path(data_dir) / 'generation-history'

    def archive_input(self, text):
        raw = text.encode('utf-8')
        sha = digest(raw)
        path = self.root / 'inputs' / (sha + '.txt')
        if path.exists():
            if path.read_bytes() != raw:
                raise PromptError('Generation input history is corrupt; original preserved.')
        else:
            storage.atomic_write(path, raw)
        return input_reference(text, 'generation-history/inputs/' + sha + '.txt')

    def write(self, record):
        import uuid
        if 'id' not in record:
            record['id'] = uuid.uuid4().hex
        if not re.fullmatch(r'[0-9a-f]{32}', record['id']):
            raise PromptError('Invalid generation attempt ID.')
        storage.atomic_write(self.root / (record['id'] + '.json'),
                             json.dumps(record, ensure_ascii=False, indent=2).encode('utf-8'))
