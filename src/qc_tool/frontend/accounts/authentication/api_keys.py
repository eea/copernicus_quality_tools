import secrets
import string

from qc_tool.frontend.accounts.models import ApiUser


API_KEY_LENGTH = 25
API_KEY_ALPHABET = string.ascii_uppercase + string.digits


def generate_api_key():
    """Return an API key generated with a cryptographically secure RNG."""

    return "".join(
        secrets.choice(API_KEY_ALPHABET) for _ in range(API_KEY_LENGTH)
    )


def get_or_create_api_key(user):
    """Return the user's existing API key or provision one lazily."""

    credential = ApiUser.objects.filter(user=user).first()
    if credential is not None:
        return credential.api_key

    api_key = generate_api_key()
    while ApiUser.objects.filter(api_key=api_key).exists():
        api_key = generate_api_key()

    credential, _created = ApiUser.objects.get_or_create(
        user=user,
        defaults={"api_key": api_key},
    )
    return credential.api_key


def authenticate_api_key(raw_key):
    """Resolve one active user for a key, failing closed on duplicates."""

    if not raw_key:
        return None

    credentials = list(
        ApiUser.objects.select_related("user").filter(api_key=raw_key)[:2]
    )
    if len(credentials) != 1:
        return None

    user = credentials[0].user
    return user if user.is_active else None


def authenticate_api_request(request):
    """Authenticate the legacy ``?apikey=`` request contract."""

    raw_key = request.GET.get("apikey")
    if not raw_key:
        return None, "api key was not provided"

    user = authenticate_api_key(raw_key)
    if user is None:
        return None, "provided api key does not match any active user"
    return user, "ok"
