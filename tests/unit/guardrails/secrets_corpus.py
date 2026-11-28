"""Synthetic secret corpora for the detector tests (M1-3 step 4b).

Everything is generated from fixed seeds. Every "secret" is random characters, never a real
credential, and no complete key appears in this file. verify_m1 (M1-12) reuses this module.
"""

from __future__ import annotations

import random
import string
from collections.abc import Callable

ALNUM = string.ascii_letters + string.digits
URLSAFE = ALNUM + "-_"
B64 = ALNUM + "+/"
UPPER_DIGITS = string.ascii_uppercase + string.digits
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
HEX = "0123456789abcdef"


def rand(rng: random.Random, alphabet: str, n: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(n))


def _with_digit(rng: random.Random, s: str) -> str:
    """Real keys virtually always contain a digit; make sure ours do."""
    if any(c.isdigit() for c in s):
        return s
    i = rng.randrange(len(s))
    return s[:i] + rng.choice(string.digits) + s[i + 1 :]


def _jwt(rng: random.Random) -> str:
    return ".".join(
        [
            "eyJ" + rand(rng, URLSAFE, rng.randint(20, 40)),
            "eyJ" + rand(rng, URLSAFE, rng.randint(20, 60)),
            rand(rng, URLSAFE, 43),
        ]
    )


# ---------------------------------------------------------------------------
# Golden positives
# ---------------------------------------------------------------------------
# format -> (expected rule id, maker)
PROVIDER_MAKERS: dict[str, tuple[str, Callable[[random.Random], str]]] = {
    "fgx": ("SEC-FGX-001", lambda r: "fgx-" + rand(r, URLSAFE, 43)),
    "groq": ("SEC-GROQ-001", lambda r: "gsk_" + rand(r, ALNUM, 52)),
    "openrouter": ("SEC-OPENROUTER-001", lambda r: "sk-or-v1-" + rand(r, ALNUM, 64)),
    "nvidia": ("SEC-NVIDIA-001", lambda r: "nvapi-" + rand(r, URLSAFE, 64)),
    "anthropic": ("SEC-ANTHROPIC-001", lambda r: "sk-ant-api03-" + rand(r, URLSAFE, 93)),
    "openai": ("SEC-OPENAI-001", lambda r: "sk-" + _with_digit(r, rand(r, ALNUM, 48))),
    "openai_proj": (
        "SEC-OPENAI-001",
        lambda r: "sk-proj-" + _with_digit(r, rand(r, URLSAFE, 100)),
    ),
    "aws": ("SEC-AWS-001", lambda r: r.choice(["AKIA", "ASIA"]) + rand(r, UPPER_DIGITS, 16)),
    "google": ("SEC-GOOGLE-001", lambda r: "AIza" + rand(r, URLSAFE, 35)),
    "github": ("SEC-GITHUB-001", lambda r: "gh" + r.choice("pousr") + "_" + rand(r, ALNUM, 36)),
    "slack": (
        "SEC-SLACK-001",
        lambda r: (
            "xox"
            + r.choice("baprs")
            + "-"
            + rand(r, string.digits, 12)
            + "-"
            + rand(r, string.digits, 12)
            + "-"
            + rand(r, ALNUM, 24)
        ),
    ),
    "jwt": ("SEC-JWT-001", _jwt),
}

_KEY_TEMPLATES = [
    "{x}",
    "key {x} end",
    "export API_KEY={x}",
    'KEY="{x}"',
    '{{"auth": "{x}"}}',
    "curl -H 'x-api-key: {x}' https://example.com",
    "use ({x}).",
]


def provider_samples(fmt: str, n: int = 200, seed: int = 11) -> list[tuple[str, str]]:
    """(text, planted key) pairs for one provider format."""
    rng = random.Random(f"{seed}-{fmt}")
    make = PROVIDER_MAKERS[fmt][1]
    samples: list[tuple[str, str]] = []
    for _ in range(n):
        value = make(rng)
        samples.append((rng.choice(_KEY_TEMPLATES).format(x=value), value))
    return samples


def bearer_samples(n: int = 300, seed: int = 12) -> list[tuple[str, str]]:
    rng = random.Random(f"{seed}-bearer")
    templates = [
        "Authorization: Bearer {x}",
        'curl -H "Authorization: Bearer {x}" https://example.com/v1/models',
        "the header Bearer {x} was rejected",
        "send Bearer {x}.",
    ]
    samples: list[tuple[str, str]] = []
    for _ in range(n):
        value = rand(rng, ALNUM, rng.randint(32, 64))
        samples.append((rng.choice(templates).format(x=value), value))
    return samples


_NAMES = [
    "api_key",
    "API_KEY",
    "client_secret",
    "password",
    "passwd",
    "pwd",
    "access_token",
    "SECRET",
    "apiKey",
    "GROQ_API_KEY",
]
_FORMS = ["{n}={v}", "{n}: {v}", '{n} = "{v}"', '"{n}": "{v}"', "{n}='{v}'"]
_PASSWORD_WORDS = [
    "tiger",
    "sunshine",
    "monkey",
    "dragon",
    "football",
    "welcome",
    "qwerty",
    "summer",
    "master",
    "freedom",
]


def assignment_samples(n: int = 300, seed: int = 13) -> list[tuple[str, str]]:
    """name=value with a random value."""
    rng = random.Random(f"{seed}-assign")
    samples: list[tuple[str, str]] = []
    for _ in range(n):
        value = rand(rng, ALNUM, rng.randint(12, 40))
        text = rng.choice(_FORMS).format(n=rng.choice(_NAMES), v=value)
        samples.append((f"config {text} # end", value))
    return samples


def human_password_samples(n: int = 200, seed: int = 14) -> list[tuple[str, str]]:
    """name=value where the value looks like a human-chosen password, e.g. Tiger2026!"""
    rng = random.Random(f"{seed}-human")
    samples: list[tuple[str, str]] = []
    for _ in range(n):
        value = (
            rng.choice(_PASSWORD_WORDS).capitalize()
            + str(rng.randint(1000, 9999))
            + rng.choice("!@#$%&")
        )
        text = rng.choice(_FORMS).format(n=rng.choice(["password", "passwd", "pwd"]), v=value)
        samples.append((f"login {text}", value))
    return samples


_PEM_KINDS = [
    "RSA PRIVATE KEY",
    "PRIVATE KEY",
    "EC PRIVATE KEY",
    "OPENSSH PRIVATE KEY",
    "ENCRYPTED PRIVATE KEY",
]


def pem_samples(n: int = 100, seed: int = 15) -> list[tuple[str, str]]:
    rng = random.Random(f"{seed}-pem")
    samples: list[tuple[str, str]] = []
    for _ in range(n):
        kind = rng.choice(_PEM_KINDS)
        lines = "\n".join(rand(rng, B64, 64) for _ in range(rng.randint(4, 24)))
        block = f"-----BEGIN {kind}-----\n{lines}\n-----END {kind}-----"
        samples.append((f"my key:\n{block}\nthanks", block))
    return samples


def entropy_samples(lo: int, hi: int, n: int = 300, seed: int = 16) -> list[tuple[str, str]]:
    """Random tokens with no prefix and no name, so only the entropy rule can find them."""
    rng = random.Random(f"{seed}-entropy-{lo}-{hi}")
    templates = ["value {x} here", "{x}", "see {x}.", "blob: {x}", "({x})"]
    samples: list[tuple[str, str]] = []
    for _ in range(n):
        alphabet = ALNUM + ("-_+/" if rng.random() < 0.3 else "")
        value = rand(rng, alphabet, rng.randint(lo, hi))
        samples.append((rng.choice(templates).format(x=value), value))
    return samples


# ---------------------------------------------------------------------------
# Benign corpus aimed at secrets
# ---------------------------------------------------------------------------
_WORDS = [
    "get", "set", "user", "account", "session", "manager", "service", "handler", "create",
    "update", "delete", "request", "response", "config", "settings", "token", "cache",
    "policy", "guard", "router", "client", "server", "query", "index", "vector", "embedding",
    "helper", "factory", "builder", "parser", "reader", "writer", "loader", "default",
    "custom", "base", "test", "mock", "fake", "error", "result", "status", "report",
    "summary", "profile", "payment", "invoice", "order", "product", "catalog",
]  # fmt: skip


def _camel(rng: random.Random) -> str:
    words = rng.sample(_WORDS, rng.randint(3, 6))
    return words[0] + "".join(w.title() for w in words[1:])


def _snake(rng: random.Random) -> str:
    return "_".join(rng.sample(_WORDS, rng.randint(4, 7)))


def _kebab(rng: random.Random) -> str:
    return "-".join(rng.sample(_WORDS, rng.randint(3, 7)))


def _upper_snake(rng: random.Random) -> str:
    return "_".join(rng.sample(_WORDS, rng.randint(3, 6))).upper()


def _long(rng: random.Random, make: Callable[[random.Random], str]) -> str:
    """An identifier of at least 20 characters (shorter ones never reach the entropy rule)."""
    s = make(rng)
    for _ in range(100):
        if len(s) >= 20:
            break
        s = make(rng)
    return s


PLACEHOLDER_LINES = [
    "API_KEY=${GROQ_API_KEY}",
    "GROQ_API_KEY=your-api-key-here",
    "OPENAI_API_KEY=<your-key>",
    "password: <your-password>",
    "token=YOUR_TOKEN_HERE",
    "client_secret: REPLACE_ME",
    "api_key = os.environ['API_KEY']",
    "password=********",
    "SECRET_KEY=changeme",
    "DB_PASSWORD=${DB_PASSWORD}",
    "Authorization: Bearer ${TOKEN}",
    "Authorization: Bearer <token>",
    "export TOKEN=$(cat token.txt)",
    "api_key: null",
    "token: undefined",
    "secret: required",
    "pwd=password",
    "passwd: example",
    "token = tokens[0]",
    "api_key=%(api_key)s",
    "{{ secrets.API_KEY }}",
    "password: str",
    "client = Groq(api_key=api_key)",
    "headers = {'Authorization': f'Bearer {token}'}",
    "password=xxxxxxxxxxxx",
]

SECURITY_PROSE = [
    "Never commit your API key to a public repository.",
    "Rotate the access token every ninety days.",
    "The password must contain at least twelve characters.",
    "Store secrets in a vault, not in source code.",
    "Bearer authentication sends the token in the Authorization header.",
    "A JWT has three parts separated by dots.",
    "Use environment variables for the API key.",
    "Tokens expire after one hour.",
    "What is the difference between a secret and a password?",
    "Explain how HMAC-SHA256 hashing protects virtual keys.",
    "Revoke the compromised key immediately and issue a new one.",
    "Do not paste passwords into chat.",
    "Private keys must never leave the server.",
    "The token endpoint returns an access token and a refresh token.",
    "OAuth uses short-lived bearer tokens.",
    "gitleaks scans commits for secrets.",
    "How do I rotate an API key without downtime?",
    "Prompt injection tries to extract the system prompt.",
    "Passwords should be hashed with a slow algorithm like bcrypt.",
    "The pepper is stored outside the database.",
    "A secret manager encrypts values at rest.",
    "Use a different key for each environment.",
    "Never share a one-time password with anyone.",
    "Keep the signing key in a hardware module.",
    "The key id is not secret but the key material is.",
]

CODE_REFS = [
    'password = input("Enter password: ")',
    "token = get_token()",
    'api_key = os.environ["API_KEY"]',
    "secret = settings.SECRET",
    "password = form.cleaned_data['password']",
    "api_key = load_key_from_vault()",
    "token = request.headers.get('X-Token')",
    "def login(password: str, token: str) -> bool:",
    "api_key: str = Field(...)",
    "password = getpass.getpass()",
    "secret = self.config.secret",
    "token = auth.issue_token(user)",
    "pwd = os.getenv('DB_PWD')",
    "passwd = prompt_for_password()",
    "api_key = config['groq']['api_key']",
    "token = jwt.encode(payload, key, algorithm='HS256')",
    "password = hasher.hash(raw_password)",
    "client_secret = secrets_manager.get('client')",
    "access_token = response.json()['access_token']",
    "secret = None",
]

ENGLISH_LONG = [
    "Supercalifragilisticexpialidocious",
    "internationalization",
    "pneumonoultramicroscopicsilicovolcanoconiosis",
    "antidisestablishmentarianism",
    "The quick brown fox jumps over the lazy dog near the riverbank",
    "incomprehensibilities and misunderstandings",
    "electroencephalographically",
    "She sells sea shells by the sea shore every single summer morning",
    "characteristically uncharacteristic",
    "counterrevolutionaries",
    "overenthusiastically",
    "The cache returns the stored answer without calling the provider again",
    "Semantic similarity does not guarantee the same meaning",
    "uncharacteristically straightforward",
    "responsibilities and accountabilities",
]


def secrets_benign_by_category() -> dict[str, list[str]]:
    rng = random.Random(20261128)
    c: dict[str, list[str]] = {}
    c["camel_identifiers"] = [f"return {_long(rng, _camel)}(request)" for _ in range(40)]
    c["snake_identifiers"] = [f"def {_long(rng, _snake)}(self):" for _ in range(40)]
    c["kebab_slugs"] = [f"https://example.com/blog/{_long(rng, _kebab)}" for _ in range(40)]
    c["file_paths"] = [
        "open('src/{}/{}/{}.py')".format(*rng.sample(_WORDS, 2), "_".join(rng.sample(_WORDS, 3)))
        for _ in range(40)
    ]
    c["constants"] = [f"{_long(rng, _upper_snake)} = 30" for _ in range(20)]
    c["css_classes"] = [f".{_long(rng, _kebab)} {{ color: red; }}" for _ in range(15)]
    c["placeholders"] = list(PLACEHOLDER_LINES)
    c["security_prose"] = list(SECURITY_PROSE)
    c["code_references"] = list(CODE_REFS)
    etag_forms = [
        f'ETag: "{rand(rng, HEX, 32)}"',
        f"docker image digest sha256:{rand(rng, HEX, 64)}",
        f"git commit {rand(rng, HEX, 40)}",
        f"checksum md5 {rand(rng, HEX, 32)}",
    ]
    c["hashes_with_labels"] = [etag_forms[i % 4] for i in range(30)]
    c["package_integrity"] = [f'"integrity": "sha512-{rand(rng, B64, 86)}=="' for _ in range(15)]
    c["image_data"] = [f"data:image/png;base64,{rand(rng, B64, 80)}" for _ in range(10)]
    c["ulids_and_request_ids"] = [
        f"trace id {rand(rng, CROCKFORD, 26)}" if i % 2 else f"req_{rand(rng, CROCKFORD, 26)}"
        for i in range(30)
    ]
    c["json_numbers"] = [
        f'{{"user_id": {rng.randint(10**6, 10**9)}, "max_tokens": {rng.randint(256, 8192)}, '
        f'"token_count": {rng.randint(1, 99999)}}}'
        for _ in range(20)
    ]
    c["english_long"] = list(ENGLISH_LONG)
    return c
